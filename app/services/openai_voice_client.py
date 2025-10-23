"""OpenAI 음성 실시간 세션과 상호작용하는 클라이언트를 제공합니다."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

import httpx
import websockets
from websockets.client import WebSocketClientProtocol

from app.config.settings import Settings
from app.services.conversation_state import ConversationStateManager
from app.utils.logging import get_logger


if TYPE_CHECKING:  # pragma: no cover - 타입 힌트 전용
    from app.services.twilio_stream_handler import TwilioStreamHandler


logger = get_logger(__name__)

MIN_COMMIT_SAMPLES = 2400  # 약 150ms 분량의 오디오 확보 후 커밋 (OpenAI 최소 100ms보다 여유있게)
COMMIT_DEBOUNCE_INTERVAL = 0.15  # seconds, to wait for additional audio before committing


@dataclass
class RealtimeSession:
    """OpenAI 실시간 세션 상태를 보관합니다."""

    websocket: WebSocketClientProtocol
    is_waiting_response: bool = False
    transcript_buffer: str = ""
    audio_buffer: List[str] = field(default_factory=list)  # base64 오디오 청크들을 로컬에 버퍼링
    pending_samples: int = 0
    last_commit_request: float = 0.0
    commit_task: Optional[asyncio.Task] = None
    session_updated: bool = False  # session.updated ACK 수신 여부


class OpenAIVoiceClient:
    """OpenAI Realtime 음성 API를 사용하여 대화형 오디오 응답을 제공합니다."""

    def __init__(self, settings: Settings, conversation_state_manager: ConversationStateManager) -> None:
        self._settings = settings
        self._conversation_state_manager = conversation_state_manager
        self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._sessions: Dict[str, RealtimeSession] = {}
        self._twilio_handler: Optional[TwilioStreamHandler] = None

    def register_twilio_handler(self, handler: "TwilioStreamHandler") -> None:
        """Twilio 스트림 핸들러를 등록하여 오디오 응답을 전달합니다."""

        self._twilio_handler = handler

    async def _flush_audio_buffer(self, stream_sid: str, session: RealtimeSession) -> None:
        """로컬 버퍼의 오디오를 OpenAI로 전송하고 커밋합니다."""

        if session.pending_samples < MIN_COMMIT_SAMPLES:
            logger.debug(
                "버퍼 플러시 스킵 - 샘플 부족",
                extra={"stream_sid": stream_sid, "pending_samples": session.pending_samples},
            )
            return

        if not session.audio_buffer:
            logger.warning("오디오 버퍼가 비어있음", extra={"stream_sid": stream_sid})
            return

        logger.debug(
            "오디오 버퍼 플러시 시작",
            extra={
                "stream_sid": stream_sid,
                "chunks": len(session.audio_buffer),
                "samples": session.pending_samples,
            },
        )

        # 버퍼링된 모든 청크를 한 번에 전송
        total_audio_bytes = 0
        chunk_count = len(session.audio_buffer)
        
        logger.debug(
            f"🔊 오디오 전송 시작: {chunk_count}개 청크",
            extra={"stream_sid": stream_sid},
        )
        
        for idx, audio_chunk in enumerate(session.audio_buffer):
            audio_bytes = base64.b64decode(audio_chunk)
            total_audio_bytes += len(audio_bytes)
            append_message = {
                "type": "input_audio_buffer.append",
                "audio": audio_chunk,
            }
            await session.websocket.send(json.dumps(append_message))
            
            if idx == 0 or idx == chunk_count - 1:
                logger.debug(
                    f"  → 청크 #{idx+1}/{chunk_count} 전송: {len(audio_bytes)} bytes",
                    extra={"stream_sid": stream_sid},
                )

        duration_ms = (total_audio_bytes // 2) / 16  # 16kHz PCM16
        logger.info(
            f"✅ 오디오 청크 전송 완료: chunks={chunk_count}, bytes={total_audio_bytes}, samples={total_audio_bytes // 2}, duration={duration_ms:.1f}ms",
            extra={"stream_sid": stream_sid},
        )

        # 버퍼 초기화
        session.audio_buffer.clear()
        session.pending_samples = 0
        
        # VAD 활성화 시에는 수동 커밋 불필요
        # OpenAI가 자동으로 음성을 감지하고 처리함
        logger.debug(
            "✅ 오디오 전송 완료 (VAD가 자동으로 음성 감지 및 응답 처리)",
            extra={"stream_sid": stream_sid},
        )

    async def _debounced_flush(self, stream_sid: str, session: RealtimeSession) -> None:
        """짧은 지연 후 버퍼를 플러시하여 충분한 오디오가 누적되도록 합니다."""

        try:
            await asyncio.sleep(COMMIT_DEBOUNCE_INTERVAL)
            await self._flush_audio_buffer(stream_sid=stream_sid, session=session)
        except asyncio.CancelledError:
            logger.debug("버퍼 플러시 예약 취소됨", extra={"stream_sid": stream_sid})
            raise
        finally:
            session.commit_task = None

    async def create_session(self, stream_sid: str, audio_format: str) -> None:
        """Twilio 스트림과 연동할 OpenAI 실시간 세션을 생성합니다."""

        print(f"\n\n🚀🚀🚀 create_session 호출됨! stream_sid={stream_sid}, audio_format={audio_format}\n\n")
        
        logger.info("OpenAI 세션 생성 시작", extra={"stream_sid": stream_sid})
        system_prompt = self._conversation_state_manager.build_system_prompt(stream_sid=stream_sid)

        try:
            # GA 버전: 직접 WebSocket 연결 (세션 생성 API 불필요)
            websocket = await self._connect_websocket_direct()
            self._sessions[stream_sid] = RealtimeSession(websocket=websocket)
            
            # 먼저 수신 태스크 시작 (session.created 이벤트 수신용)
            asyncio.create_task(self._receive_and_forward(stream_sid=stream_sid))
            
            # session.created 이벤트를 기다림
            await asyncio.sleep(0.1)
            
            # 세션 설정 업데이트 - system prompt 및 오디오 포맷 설정
            await self._configure_session(
                stream_sid=stream_sid,
                session=self._sessions[stream_sid],
                system_prompt=system_prompt,
            )
            
            logger.info("OpenAI 세션 준비 완료 - VAD 자동 응답 모드", extra={"stream_sid": stream_sid})
        except Exception:  # pylint: disable=broad-except
            logger.exception("OpenAI 세션 생성 중 알 수 없는 오류", extra={"stream_sid": stream_sid})
            raise

    async def send_audio_chunk(self, stream_sid: str, audio_chunk_b64: str) -> None:
        """Twilio에서 수신한 base64 오디오 데이터를 로컬 버퍼에 저장합니다."""

        session = self._sessions.get(stream_sid)
        if not session:
            logger.warning("세션이 존재하지 않아 오디오 전송 불가", extra={"stream_sid": stream_sid})
            return

        try:
            audio_bytes = base64.b64decode(audio_chunk_b64)
        except (ValueError, TypeError) as error:
            logger.warning("OpenAI로 전송할 오디오 base64 디코딩 실패", extra={"stream_sid": stream_sid, "error": str(error)})
            return

        # 로컬 버퍼에 추가 (OpenAI로 즉시 전송하지 않음)
        session.audio_buffer.append(audio_chunk_b64)
        session.pending_samples += len(audio_bytes) // 2  # 2 bytes per sample (PCM16 mono)

        # 충분한 샘플이 누적되면 플러시 예약
        if session.pending_samples >= MIN_COMMIT_SAMPLES:
            session.last_commit_request = asyncio.get_event_loop().time()
            if session.commit_task and not session.commit_task.done():
                session.commit_task.cancel()
            session.commit_task = asyncio.create_task(
                self._debounced_flush(stream_sid=stream_sid, session=session)
            )
            logger.debug(
                "버퍼 플러시 예약",
                extra={
                    "stream_sid": stream_sid,
                    "pending_samples": session.pending_samples,
                    "buffer_chunks": len(session.audio_buffer),
                },
            )

    async def close_session(self, stream_sid: str) -> None:
        """OpenAI 세션을 종료합니다."""

        logger.info("OpenAI 세션 종료", extra={"stream_sid": stream_sid})
        session = self._sessions.pop(stream_sid, None)
        if session:
            # 예약된 플러시 태스크 취소
            if session.commit_task and not session.commit_task.done():
                session.commit_task.cancel()
                try:
                    await session.commit_task
                except asyncio.CancelledError:
                    pass
                except Exception:  # pylint: disable=broad-except
                    logger.exception("플러시 태스크 취소 중 오류", extra={"stream_sid": stream_sid})
            
            # 잠시 대기하여 진행 중인 작업 완료
            await asyncio.sleep(0.01)
            
            # 버퍼에 충분한 샘플이 남아있으면 마지막으로 플러시
            if session.pending_samples >= MIN_COMMIT_SAMPLES and session.audio_buffer:
                try:
                    logger.debug(
                        "종료 시 잔여 버퍼 플러시",
                        extra={
                            "stream_sid": stream_sid,
                            "pending_samples": session.pending_samples,
                            "buffer_chunks": len(session.audio_buffer),
                        },
                    )
                    await self._flush_audio_buffer(stream_sid=stream_sid, session=session)
                except Exception:  # pylint: disable=broad-except
                    logger.warning("종료 시 버퍼 플러시 중 오류", extra={"stream_sid": stream_sid})
            else:
                logger.debug(
                    "종료 시 버퍼 플러시 스킵 - 샘플 부족",
                    extra={
                        "stream_sid": stream_sid,
                        "pending_samples": session.pending_samples,
                        "buffer_chunks": len(session.audio_buffer),
                    },
                )
            
            # 버퍼 정리
            session.audio_buffer.clear()
            session.pending_samples = 0
            await session.websocket.close()

    async def _configure_session(self, stream_sid: str, session: RealtimeSession, system_prompt: str) -> None:
        """WebSocket 연결 후 세션을 구성합니다 (system prompt, 오디오 포맷 등)."""
        
        logger.info(
            f"🔍 전송할 System Prompt: {system_prompt[:100]}...",
            extra={"stream_sid": stream_sid},
        )
        
        # 1단계: session.update 전송
        update_message = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": system_prompt,
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 700  # 700ms 침묵 후 말이 끝났다고 판단
                },
                "temperature": 0.6,
                "max_response_output_tokens": 200,
            },
        }
        await session.websocket.send(json.dumps(update_message))
        logger.info("✅ session.update 전송 완료", extra={"stream_sid": stream_sid})
        
        # 2단계: session.updated ACK 대기 (최대 2초)
        session_updated = False
        for _ in range(20):  # 0.1초씩 20번 = 2초
            await asyncio.sleep(0.1)
            # _receive_and_forward에서 session.updated를 받으면 플래그 설정
            if hasattr(session, 'session_updated') and session.session_updated:
                session_updated = True
                break
        
        if not session_updated:
            logger.warning("⚠️ session.updated ACK를 받지 못함 - 설정이 적용되지 않았을 수 있음", extra={"stream_sid": stream_sid})
        else:
            logger.info("✅ session.updated ACK 수신 완료", extra={"stream_sid": stream_sid})
        
        # 3단계: conversation.item.create로 system 메시지 추가 (중복 안전망)
        system_message = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "항상 한국어(존댓말)로만 응답하세요. 영어, 스페인어, 프랑스어, 아랍어 등 다른 언어는 절대 사용 금지입니다."
                    }
                ]
            }
        }
        await session.websocket.send(json.dumps(system_message))
        logger.info("✅ system 메시지 추가 완료", extra={"stream_sid": stream_sid})
        
        await asyncio.sleep(0.2)  # conversation.item.created ACK 대기
        
        logger.info(
            "OpenAI 세션 설정 완료 (3단계)",
            extra={"stream_sid": stream_sid, "voice": "alloy", "format": "pcm16@16kHz"},
        )

    async def _request_response(self, stream_sid: str, session: RealtimeSession) -> None:
        """OpenAI에 음성 응답 생성을 요청합니다."""

        # 응답 레벨에서도 한국어 강제 (3중 안전망)
        response_request = {
            "type": "response.create",
            "response": {
                "instructions": "지금부터 한국어(존댓말)로만 응답하세요. 다른 언어 사용 금지."
            }
        }
        await session.websocket.send(json.dumps(response_request))
        session.is_waiting_response = True
        
        logger.info(
            "OpenAI 응답 생성 요청 전송 (한국어 강제)",
            extra={"stream_sid": stream_sid},
        )

    async def _connect_websocket_direct(self) -> WebSocketClientProtocol:
        """OpenAI Realtime WebSocket에 직접 연결합니다 (GA 버전)."""

        realtime_url = f"wss://api.openai.com/v1/realtime?model={self._settings.openai_realtime_model}"
        
        # API 키 마스킹 (처음 10자, 마지막 4자만 표시)
        api_key = self._settings.openai_api_key
        masked_key = f"{api_key[:10]}...{api_key[-4:]}" if len(api_key) > 14 else "***"
        
        logger.info(
            f"🔍 DEBUG: 사용 중인 설정",
            extra={
                "model": self._settings.openai_realtime_model,
                "api_key_prefix": masked_key,
            },
        )
        
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        logger.debug(f"WebSocket 연결 시도: {realtime_url}")
        websocket = await websockets.connect(realtime_url, additional_headers=headers, max_size=None)
        logger.info("OpenAI Realtime WebSocket 연결 성공")
        return websocket

    async def _receive_and_forward(self, stream_sid: str) -> None:
        """OpenAI 응답을 수신하고 Twilio로 전달하는 흐름을 유지합니다."""

        session = self._sessions.get(stream_sid)
        if not session:
            logger.warning("OpenAI 세션이 존재하지 않아 수신 루프를 종료합니다.", extra={"stream_sid": stream_sid})
            return

        websocket = session.websocket

        try:
            async for message in websocket:
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("OpenAI 응답 파싱 실패", extra={"stream_sid": stream_sid})
                    continue

                event_type = payload.get("type")

                # 모든 이벤트 타입을 명확하게 로깅
                logger.info(
                    f"📨 OpenAI 이벤트: {event_type}",
                    extra={"stream_sid": stream_sid, "event_type": event_type},
                )

                if event_type == "session.created":
                    # WebSocket 연결 직후 첫 이벤트
                    logger.info(
                        "✅ OpenAI 세션 생성 완료 (session.created)",
                        extra={"stream_sid": stream_sid},
                    )
                elif event_type == "session.updated":
                    # 세션 설정 업데이트 확인 - 플래그 설정
                    session.session_updated = True
                    session_data = payload.get("session", {})
                    logger.info(
                        f"✅ session.updated 수신! voice={session_data.get('voice')}, "
                        f"modalities={session_data.get('modalities')}",
                        extra={"stream_sid": stream_sid}
                    )
                elif event_type == "input_audio_buffer.committed":
                    # 사용자 오디오 커밋 확인
                    logger.info(
                        "✅ 사용자 오디오 커밋됨 (OpenAI 확인)",
                        extra={"stream_sid": stream_sid},
                    )
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # 사용자 음성 트랜스크립트 완료
                    transcript = payload.get("transcript", "")
                    logger.error(
                        f"🎤 사용자 말함: {transcript}",
                        extra={"stream_sid": stream_sid},
                    )
                elif event_type == "response.created":
                    # 응답 생성이 시작되었음을 확인
                    logger.info(
                        "OpenAI 응답 생성 시작",
                        extra={"stream_sid": stream_sid, "response_id": payload.get("response", {}).get("id")},
                    )
                elif event_type == "response.output_audio.delta":
                    # 핵심: response.output_audio.delta!
                    audio_delta = payload.get("delta")
                    logger.error(
                        f"🎵 response.output_audio.delta 수신! delta={audio_delta[:50] if audio_delta else None}..., has_handler={bool(self._twilio_handler)}",
                        extra={"stream_sid": stream_sid},
                    )
                    if audio_delta and self._twilio_handler:
                        logger.info(
                            "✅ OpenAI 오디오 델타 수신 → Twilio 전송",
                            extra={"stream_sid": stream_sid, "payload_length": len(audio_delta)},
                        )
                        await self._twilio_handler.send_audio_to_twilio(
                            stream_sid=stream_sid,
                            audio_payload_b64=audio_delta,
                        )
                    else:
                        logger.warning(
                            "오디오 델타가 비어있거나 Twilio 핸들러 없음",
                            extra={"stream_sid": stream_sid, "has_delta": bool(audio_delta), "has_handler": bool(self._twilio_handler)},
                        )
                elif event_type == "response.output_audio.done":
                    logger.info(
                        "OpenAI 오디오 출력 완료",
                        extra={"stream_sid": stream_sid},
                    )
                elif event_type == "response.output_item.added":
                    # 출력 아이템 추가 이벤트
                    logger.error(
                        f"🔍 DEBUG: response.output_item.added - {payload.get('item', {}).get('type')}",
                        extra={"stream_sid": stream_sid},
                    )
                elif event_type == "response.content_part.added":
                    # 콘텐츠 파트 추가 이벤트
                    logger.error(
                        f"🔍 DEBUG: response.content_part.added - {payload.get('part', {}).get('type')}",
                        extra={"stream_sid": stream_sid},
                    )
                elif event_type == "response.output_audio_transcript.delta":
                    # 오디오의 텍스트 변환본
                    transcript_delta = payload.get("delta", "")
                    print(f"🗣️ AI 말하는 중: {transcript_delta}")
                    logger.error(
                        f"🗣️ AI 트랜스크립트: {transcript_delta}",
                        extra={"stream_sid": stream_sid, "transcript": transcript_delta},
                    )
                elif event_type == "response.output_text.delta":
                    text_delta = payload.get("delta", "")
                    session.transcript_buffer += text_delta
                elif event_type == "response.done":
                    # 응답 완료
                    session.is_waiting_response = False
                    response_data = payload.get("response", {})
                    
                    # 디버깅: 전체 response 구조 출력
                    output_items = response_data.get("output", [])
                    logger.error(
                        f"🔍 DEBUG 응답완료: status={response_data.get('status')}, "
                        f"status_details={response_data.get('status_details')}, "
                        f"output_count={len(output_items)}, "
                        f"output_types={[item.get('type') for item in output_items] if output_items else 'none'}, "
                        f"usage={response_data.get('usage')}"
                    )
                    if session.transcript_buffer:
                        self._conversation_state_manager.update_context(
                            stream_sid=stream_sid,
                            key="last_ai_response",
                            value=session.transcript_buffer,
                        )
                        session.transcript_buffer = ""
                elif event_type == "response.completed":
                    session.is_waiting_response = False
                    if session.transcript_buffer:
                        self._conversation_state_manager.update_context(
                            stream_sid=stream_sid,
                            key="last_ai_response",
                            value=session.transcript_buffer,
                        )
                        session.transcript_buffer = ""
                elif event_type == "response.error":
                    logger.error(
                        "OpenAI 응답 오류: %s",
                        payload.get("error"),
                        extra={"stream_sid": stream_sid},
                    )
                    session.is_waiting_response = False
                elif event_type == "error":
                    logger.error(
                        "OpenAI 일반 오류 이벤트: %s",
                        payload,
                        extra={"stream_sid": stream_sid},
                    )
                    session.is_waiting_response = False

        except websockets.ConnectionClosed:
            logger.info("OpenAI WebSocket 연결 종료", extra={"stream_sid": stream_sid})
        except Exception:  # pylint: disable=broad-except
            logger.exception("OpenAI 응답 수신 중 오류", extra={"stream_sid": stream_sid})



