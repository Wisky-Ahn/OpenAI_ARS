"""애플리케이션 전역 설정을 관리하고 제공합니다."""

from functools import lru_cache
from typing import Optional

from pydantic import AnyUrl, Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경 변수에서 로드된 ARS 시스템 설정 값을 제공합니다."""

    environment: str = Field(default="development")

    twilio_account_sid: str = Field(..., alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(..., alias="TWILIO_AUTH_TOKEN")
    twilio_api_key_sid: str = Field(..., alias="TWILIO_API_KEY_SID")
    twilio_api_key_secret: str = Field(..., alias="TWILIO_API_KEY_SECRET")
    twilio_voice_application_sid: Optional[str] = Field(None, alias="TWILIO_VOICE_APPLICATION_SID")
    twilio_stream_endpoint: AnyUrl = Field(..., alias="TWILIO_STREAM_ENDPOINT")

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_realtime_model: str = Field(default="gpt-realtime")
    openai_response_voice: str = Field(default="alloy")
    openai_response_format: str = Field(default="wav")

    app_public_base_url: HttpUrl = Field(..., alias="APP_PUBLIC_BASE_URL")

    max_retry_count: int = Field(default=3, alias="MAX_RETRY_COUNT")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", populate_by_name=True)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        """환경 값이 허용된 목록인지 검증합니다."""

        allowed_environments = {"development", "staging", "production"}
        if value not in allowed_environments:
            raise ValueError(f"Invalid environment '{value}' - choose from {allowed_environments}")
        return value


@lru_cache()
def get_settings() -> Settings:
    """Settings 객체를 캐싱하여 반환합니다."""

    return Settings()


