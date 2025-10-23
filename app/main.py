"""FastAPI 애플리케이션 엔트리포인트를 정의합니다."""

from fastapi import FastAPI

from app.config.settings import get_settings
from app.routes.voice import configure_voice_routes
from app.services.twilio_stream_handler import TwilioStreamHandler
from app.services.openai_voice_client import OpenAIVoiceClient
from app.services.conversation_state import ConversationStateManager
from app.utils.logging import configure_logging


def create_app() -> FastAPI:
    """FastAPI 애플리케이션을 생성하고 필수 의존성을 주입합니다."""

    settings = get_settings()
    configure_logging()

    app = FastAPI(title="ARS AI Voice", version="0.1.0")

    conversation_state_manager = ConversationStateManager()
    openai_client = OpenAIVoiceClient(settings=settings, conversation_state_manager=conversation_state_manager)
    twilio_handler = TwilioStreamHandler(
        settings=settings,
        conversation_state_manager=conversation_state_manager,
        openai_client=openai_client,
    )

    openai_client.register_twilio_handler(twilio_handler)

    configure_voice_routes(
        app=app,
        settings=settings,
        twilio_handler=twilio_handler,
    )

    return app


app = create_app()


