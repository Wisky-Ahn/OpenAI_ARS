"""오디오 인코딩 변환 유틸리티를 제공합니다."""

import base64
import audioop
from typing import Literal

SUPPORTED_ENCODINGS = Literal["audio/x-mulaw", "audio/x-alaw", "audio/x-raw", "audio/L16"]

TWILIO_DEFAULT_ENCODING = "audio/x-mulaw"
TWILIO_DEFAULT_SAMPLE_RATE = 8000
OPENAI_DEFAULT_SAMPLE_RATE = 16000


def convert_audio_to_pcm16(
    media_chunk_b64: str,
    encoding: str,
    source_sample_rate: int,
    target_sample_rate: int = OPENAI_DEFAULT_SAMPLE_RATE,
) -> str:
    """Twilio에서 전달된 오디오를 PCM16(16kHz)로 변환 후 base64 문자열로 반환합니다."""

    raw_bytes = base64.b64decode(media_chunk_b64)

    if encoding == "audio/x-mulaw":
        pcm16_bytes = audioop.ulaw2lin(raw_bytes, 2)
    elif encoding == "audio/x-alaw":
        pcm16_bytes = audioop.alaw2lin(raw_bytes, 2)
    elif encoding in {"audio/x-raw", "audio/L16"}:
        pcm16_bytes = raw_bytes
    else:
        raise ValueError(f"Unsupported audio encoding: {encoding}")

    if source_sample_rate != target_sample_rate:
        pcm16_bytes, _ = audioop.ratecv(
            pcm16_bytes,
            2,
            1,
            source_sample_rate,
            target_sample_rate,
            None,
        )

    return base64.b64encode(pcm16_bytes).decode("ascii")


def convert_pcm16_to_mulaw(
    audio_chunk_b64: str,
    source_sample_rate: int = OPENAI_DEFAULT_SAMPLE_RATE,
    target_sample_rate: int = TWILIO_DEFAULT_SAMPLE_RATE,
) -> str:
    """OpenAI PCM16 응답을 Twilio가 요구하는 μ-law 8kHz로 변환합니다."""

    raw_bytes = base64.b64decode(audio_chunk_b64)

    if source_sample_rate != target_sample_rate:
        raw_bytes, _ = audioop.ratecv(
            raw_bytes,
            2,
            1,
            source_sample_rate,
            target_sample_rate,
            None,
        )

    mulaw_bytes = audioop.lin2ulaw(raw_bytes, 2)
    return base64.b64encode(mulaw_bytes).decode("ascii")
