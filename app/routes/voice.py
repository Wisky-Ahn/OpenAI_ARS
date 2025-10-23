"""Twilio 음성 웹훅 라우트를 정의하고 TwiML을 반환합니다."""

from typing import Optional
import json

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, WebSocket
from fastapi.responses import PlainTextResponse
from starlette.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect

from app.config.settings import Settings, get_settings
from app.services.twilio_stream_handler import TwilioStreamHandler
from app.utils.logging import get_logger


router = APIRouter()
logger = get_logger(__name__)
_twilio_handler: Optional[TwilioStreamHandler] = None


def configure_voice_routes(app: FastAPI, settings: Settings, twilio_handler: TwilioStreamHandler) -> None:
    """ARS용 Twilio 음성 라우트를 FastAPI 애플리케이션에 등록합니다."""

    global _twilio_handler  # pylint: disable=global-statement
    _twilio_handler = twilio_handler
    app.include_router(router, prefix="/twilio", tags=["voice"])


def get_twilio_handler() -> TwilioStreamHandler:
    """등록된 Twilio 스트림 핸들러 인스턴스를 반환합니다."""

    if _twilio_handler is None:  # pragma: no cover - 실행 시점 예외 케이스
        raise RuntimeError("TwilioStreamHandler is not configured")
    return _twilio_handler


@router.post("/voice", response_class=PlainTextResponse)
async def handle_incoming_call(
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    """Twilio에서 수신된 전화에 대해 스트리밍 연결을 설정하는 TwiML을 반환합니다."""

    try:
        response = VoiceResponse()
        response.say(
            "안녕하세요. 상담을 연결해드리겠습니다. 잠시만 기다려 주세요.",
            language="ko-KR",
            voice="Polly.Seoyeon-Neural",
        )

        connect = Connect()
        connect.stream(url=str(settings.twilio_stream_endpoint))
        response.append(connect)

        return PlainTextResponse(str(response), media_type="text/xml")

    except Exception:  # pylint: disable=broad-except
        logger.exception("Twilio voice webhook 처리 중 오류 발생")

        fallback_response = VoiceResponse()
        fallback_response.say(
            "시스템에 문제가 발생했습니다. 잠시 후 다시 전화해 주세요.",
            language="ko-KR",
            voice="Polly.Seoyeon-Neural",
        )
        fallback_response.pause(length=1)
        fallback_response.say(
            "문제가 계속되면 상담원 연결을 위해 일반 고객센터 번호로 연락 부탁드립니다.",
            language="ko-KR",
            voice="Polly.Seoyeon-Neural",
        )

        return PlainTextResponse(str(fallback_response), media_type="text/xml", status_code=status.HTTP_200_OK)


@router.websocket("/stream")
async def handle_twilio_stream(
    websocket: WebSocket,
    twilio_handler: TwilioStreamHandler = Depends(get_twilio_handler),
) -> None:
    """Twilio Media Stream WebSocket 이벤트를 처리합니다."""

    await websocket.accept()
    logger.info("Twilio Media Stream WebSocket 연결 수립")

    stream_sid = None

    try:
        while True:
            try:
                message_text = await websocket.receive_text()
            except WebSocketDisconnect as disconnect:
                logger.info(
                    "Twilio WebSocket 연결 종료 신호 수신",
                    extra={"stream_sid": stream_sid, "code": disconnect.code},
                )
                break

            if not message_text:
                logger.debug("빈 WebSocket 메시지 수신, 무시", extra={"stream_sid": stream_sid})
                continue

            try:
                payload = json.loads(message_text)
            except json.JSONDecodeError:
                logger.warning(
                    "Twilio WebSocket 메시지 JSON 파싱 실패",
                    extra={"stream_sid": stream_sid, "snippet": message_text[:100]},
                )
                continue

            event_type = payload.get("event")

            if event_type == "start":
                stream_sid = payload.get("start", {}).get("streamSid")
                if not stream_sid:
                    logger.warning("start 이벤트에 streamSid 없음", extra={"payload": payload})
                    continue

                await twilio_handler.register_stream(stream_sid=stream_sid, websocket=websocket)
                media_format = payload.get("start", {}).get("mediaFormat") or payload.get("start", {}).get("media_format")
                if media_format:
                    logger.debug(
                        "Twilio mediaFormat 수신",
                        extra={
                            "stream_sid": stream_sid,
                            "encoding": media_format.get("encoding"),
                            "sample_rate": media_format.get("sampleRate") or media_format.get("sample_rate"),
                        },
                    )
                    twilio_handler.configure_stream_audio(
                        stream_sid=stream_sid,
                        encoding=media_format.get("encoding"),
                        sample_rate=media_format.get("sampleRate") or media_format.get("sample_rate"),
                    )

                await twilio_handler.start_session(stream_sid=stream_sid)
                logger.info("Twilio 스트림 시작", extra={"stream_sid": stream_sid})

            elif event_type == "media":
                media_data = payload.get("media", {}).get("payload")
                if stream_sid and media_data:
                    # 원본 오디오 데이터 샘플 로깅
                    logger.debug(
                        f"Twilio media 청크 수신: len={len(media_data)}, sample={media_data[:50]}...",
                        extra={"stream_sid": stream_sid, "payload_length": len(media_data)},
                    )
                    await twilio_handler.forward_media_chunk(stream_sid=stream_sid, media_chunk_b64=media_data)
                else:
                    logger.debug(
                        "media 이벤트에 payload 누락", extra={"stream_sid": stream_sid, "payload": payload}
                    )

            elif event_type == "stop":
                logger.info("Twilio 스트림 종료 요청", extra={"stream_sid": stream_sid})
                break

            else:
                logger.debug("알 수 없는 이벤트 수신", extra={"stream_sid": stream_sid, "event": event_type})

    except Exception:  # pylint: disable=broad-except
        logger.exception("Twilio Media Stream 처리 중 오류")
    finally:
        if stream_sid:
            await twilio_handler.terminate_session(stream_sid=stream_sid)
        try:
            await websocket.close()
        except RuntimeError:
            # 이미 종료된 상태면 RuntimeError가 발생할 수 있으므로 무시
            pass
        except WebSocketDisconnect:
            pass
