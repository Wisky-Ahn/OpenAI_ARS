# ARS AI Voice 콜 플로우 개요

## 전체 흐름

1. 발신자가 Twilio 번호 `+1 276 566 0155`로 전화
2. Twilio Voice Webhook (`/twilio/voice`) 호출 → `<Connect><Stream>` TwiML 반환
3. Twilio Media Streams가 `wss://<APP_PUBLIC_BASE_URL>/twilio/stream` WebSocket으로 연결
4. `TwilioStreamHandler`가 오디오를 수신하여 `OpenAIVoiceClient`에 전달
5. OpenAI Realtime API가 음성/텍스트 응답 생성 → Twilio Media Stream으로 재송신
6. 콜 종료 시 세션/컨텍스트/연결 정리

## 주요 컴포넌트

- `app/routes/voice.py`
  - `/twilio/voice`: 콜 시작 시 TwiML 생성
  - `/twilio/stream`: Twilio Media Stream WebSocket 처리
- `app/services/twilio_stream_handler.py`: Twilio ↔ OpenAI 브리지
- `app/services/openai_voice_client.py`: OpenAI Realtime 세션 및 오디오 입출력 관리
- `app/services/conversation_state.py`: 세션별 컨텍스트 및 시스템 프롬프트 관리

## 환경 변수 요약

| 변수 | 설명 |
| --- | --- |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_API_KEY_SID` | Twilio API Key SID (Media Streams) |
| `TWILIO_API_KEY_SECRET` | Twilio API Key Secret |
| `TWILIO_STREAM_ENDPOINT` | Twilio Media Stream WebSocket URL |
| `OPENAI_API_KEY` | OpenAI API Key |
| `OPENAI_REALTIME_MODEL` | (선택) 사용할 Realtime 모델, 기본 `gpt-4o-realtime-preview-2024-12` |
| `OPENAI_RESPONSE_VOICE` | (선택) 응답 음성, 기본 `alloy` |
| `OPENAI_RESPONSE_FORMAT` | (선택) 응답 오디오 포맷, 기본 `wav` |
| `APP_PUBLIC_BASE_URL` | 공개 접근 가능한 FastAPI 서버 베이스 URL |

## 테스트 및 검증

- `tests/test_voice_route.py`: TwiML 생성 유닛 테스트 포함
- `pytest` 실행으로 회귀 여부 확인
- 실제 콜 검증은 Twilio 콘솔 또는 SIP 클라이언트로 테스트


