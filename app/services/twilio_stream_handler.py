"""Twilio Media Stream과 OpenAI 음성 세션 간 브리지를 제공합니다."""

from typing import Dict

from fastapi import WebSocket

from app.config.settings import Settings
from app.services.openai_voice_client import OpenAIVoiceClient
from app.services.conversation_state import ConversationStateManager
from app.utils.audio import convert_audio_to_pcm16, convert_pcm16_to_mulaw
from app.utils.logging import get_logger


logger = get_logger(__name__)


class TwilioStreamHandler:
    """Twilio WebSocket 스트림을 관리하고 오디오를 OpenAI 형식으로 변환합니다."""

    def __init__(
        self,
        settings: Settings,
        conversation_state_manager: ConversationStateManager,
        openai_client: OpenAIVoiceClient,
    ) -> None:
        self._settings = settings
        self._conversation_state_manager = conversation_state_manager
        self._openai_client = openai_client
        self._twilio_connections: Dict[str, WebSocket] = {}
        self._stream_audio_config: Dict[str, Dict[str, int | str]] = {}

    async def register_stream(self, stream_sid: str, websocket: WebSocket) -> None:
        """Twilio WebSocket을 세션에 등록합니다."""

        logger.debug("Twilio 스트림 WebSocket 등록", extra={"stream_sid": stream_sid})
        self._twilio_connections[stream_sid] = websocket
        self._stream_audio_config[stream_sid] = {
            "encoding": "audio/x-mulaw",
            "sample_rate": 8000,
        }

    def configure_stream_audio(self, stream_sid: str, encoding: str | None, sample_rate: int | None) -> None:
        """Twilio 스트림에서 제공한 오디오 포맷 정보를 저장합니다."""

        audio_config = self._stream_audio_config.get(stream_sid)
        if audio_config is None:
            logger.warning("오디오 포맷 설정 시 스트림 정보가 존재하지 않습니다.", extra={"stream_sid": stream_sid})
            return

        if encoding:
            audio_config["encoding"] = encoding
        if sample_rate:
            audio_config["sample_rate"] = sample_rate

    async def start_session(self, stream_sid: str) -> None:
        """새로운 Twilio 스트림에 대한 OpenAI 세션을 시작합니다."""

        logger.info("Twilio 스트림 세션 시작", extra={"stream_sid": stream_sid})
        await self._openai_client.create_session(stream_sid=stream_sid, audio_format="pcm16")

    async def forward_media_chunk(self, stream_sid: str, media_chunk_b64: str) -> None:
        """Twilio에서 전달된 base64 오디오 청크를 OpenAI 세션으로 전달합니다."""

        try:
            audio_config = self._stream_audio_config.get(stream_sid)
            if audio_config is None:
                logger.warning("오디오 포맷 정보가 없어 청크를 전송할 수 없습니다.", extra={"stream_sid": stream_sid})
                return

            converted_chunk = convert_audio_to_pcm16(
                media_chunk_b64=media_chunk_b64,
                encoding=str(audio_config["encoding"]),
                source_sample_rate=int(audio_config["sample_rate"]),
                target_sample_rate=16000,
            )

            logger.debug(
                "OpenAI 전송 오디오 변환 완료",
                extra={
                    "stream_sid": stream_sid,
                    "payload_length": len(converted_chunk),
                    "encoding": audio_config.get("encoding"),
                },
            )

            await self._openai_client.send_audio_chunk(stream_sid=stream_sid, audio_chunk_b64=converted_chunk)
        except Exception:  # pylint: disable=broad-except
            logger.exception("오디오 청크 전달 중 오류", extra={"stream_sid": stream_sid})

    async def send_audio_to_twilio(self, stream_sid: str, audio_payload_b64: str) -> None:
        """OpenAI 응답 오디오(base64)를 Twilio로 전송합니다."""

        websocket = self._twilio_connections.get(stream_sid)
        if not websocket:
            logger.warning("Twilio WebSocket 미등록", extra={"stream_sid": stream_sid})
            return

        audio_config = self._stream_audio_config.get(stream_sid, {})
        try:
            # OpenAI는 24kHz PCM16으로 오디오를 보냄
            twilio_payload = convert_pcm16_to_mulaw(
                audio_chunk_b64=audio_payload_b64,
                source_sample_rate=24000,  # OpenAI의 출력 샘플 레이트
                target_sample_rate=8000,   # Twilio의 μ-law 샘플 레이트
            )
            logger.debug(
                "Twilio 전송 오디오 변환 완료",
                extra={
                    "stream_sid": stream_sid,
                    "payload_length": len(twilio_payload),
                    "source_sample_rate": audio_config.get("sample_rate", 16000),
                },
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("OpenAI 오디오를 Twilio 포맷으로 변환 중 오류", extra={"stream_sid": stream_sid})
            return

        message = {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": twilio_payload},
        }
        await websocket.send_json(message)

    async def terminate_session(self, stream_sid: str) -> None:
        """스트림 종료 시 OpenAI 세션과 Twilio 연결을 정리합니다."""

        logger.info("Twilio 스트림 세션 종료", extra={"stream_sid": stream_sid})
        try:
            await self._openai_client.close_session(stream_sid=stream_sid)
        finally:
            self._twilio_connections.pop(stream_sid, None)
            self._stream_audio_config.pop(stream_sid, None)
            self._conversation_state_manager.clear(stream_sid)


