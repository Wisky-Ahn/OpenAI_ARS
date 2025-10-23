# ARS AI Voice 서버

Twilio Media Streams와 OpenAI Realtime Voice API를 결합한 FastAPI 기반 실시간 음성 ARS 시스템입니다. 
발신자가 Twilio 번호로 전화하면 AI 상담원과 한국어로 실시간 음성 대화를 진행할 수 있습니다.

## 주요 기능

- ✅ **실시간 음성 대화**: OpenAI Realtime API를 통한 자연스러운 대화
- ✅ **한국어 지원**: 한국어 존댓말로 응답하는 AI 상담원
- ✅ **VAD (Voice Activity Detection)**: 자동 음성 감지 및 응답
- ✅ **오디오 포맷 변환**: μ-law ↔ PCM16 자동 변환
- ✅ **WebSocket 스트리밍**: Twilio Media Streams를 통한 실시간 오디오 전송

## 구성 요소

- `app/main.py`: FastAPI 엔트리포인트, 의존성 주입
- `app/routes/voice.py`: Twilio Voice Webhook 및 Media Stream WebSocket 라우트
- `app/services/openai_voice_client.py`: OpenAI Realtime API 클라이언트 (VAD 지원)
- `app/services/twilio_stream_handler.py`: Twilio ↔ OpenAI 오디오 브리지
- `app/services/conversation_state.py`: 대화 상태 및 시스템 프롬프트 관리
- `app/utils/audio.py`: 오디오 포맷 변환 유틸리티 (μ-law, PCM16)
- `app/config/settings.py`: 환경 변수 및 설정 관리

## 시스템 요구사항

- Python 3.12+
- Twilio 계정 (Phone Number, API Keys)
- OpenAI API 키 (Realtime API 접근 권한 필요)
- ngrok 또는 공개 도메인 (로컬 테스트 시)

## 설치 및 실행

### 1. 가상환경 설정

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일을 프로젝트 루트에 생성하고 아래 값을 설정합니다:

```env
# Twilio 설정 (필수)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SECRET=your_api_key_secret

# OpenAI 설정 (필수)
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 서버 설정 (필수)
APP_PUBLIC_BASE_URL=https://your-domain.com
TWILIO_STREAM_ENDPOINT=wss://your-domain.com/twilio/stream

# 선택 옵션 (기본값이 있으므로 생략 가능)
OPENAI_REALTIME_MODEL=gpt-realtime  # 기본값: gpt-4o-realtime-preview-2024-12
OPENAI_RESPONSE_VOICE=alloy         # 기본값: alloy
OPENAI_RESPONSE_FORMAT=wav          # 기본값: wav
MAX_RETRY_COUNT=3                   # 기본값: 3
ENVIRONMENT=development             # 기본값: development
```

### 3. 서버 실행

```bash
# 개발 모드 (자동 재시작)
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# 프로덕션 모드
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### 4. ngrok으로 로컬 테스트 (선택)

```bash
# ngrok 설치 (Homebrew)
brew install --cask ngrok

# ngrok 실행
ngrok http 8080

# ngrok URL을 .env의 APP_PUBLIC_BASE_URL과 TWILIO_STREAM_ENDPOINT에 설정
```

## Twilio 설정

### 1. TwiML Bin 생성

Twilio Console → TwiML Bins → Create new TwiML Bin

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://your-domain.com/twilio/stream" />
    </Connect>
</Response>
```

### 2. Phone Number 설정

Twilio Console → Phone Numbers → Active Numbers → 해당 번호 선택

- **Voice Configuration**:
  - A CALL COMES IN: TwiML Bin → 위에서 생성한 TwiML Bin 선택
  - SAVE 클릭

## 아키텍처

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   전화 발신   │ ──────> │    Twilio    │ ──────> │  FastAPI    │
│   (사용자)   │ <────── │ Media Stream │ <────── │   서버      │
└─────────────┘         └──────────────┘         └─────────────┘
                                                         │
                                                         │ WebSocket
                                                         ↓
                                                  ┌─────────────┐
                                                  │   OpenAI    │
                                                  │ Realtime API│
                                                  └─────────────┘
```

### 오디오 흐름

1. **사용자 → Twilio**: 전화 음성 (μ-law, 8kHz)
2. **Twilio → 서버**: WebSocket Media Stream (μ-law, 8kHz)
3. **서버 → OpenAI**: 변환된 오디오 (PCM16, 16kHz)
4. **OpenAI → 서버**: AI 응답 오디오 (PCM16, 24kHz)
5. **서버 → Twilio**: 변환된 오디오 (μ-law, 8kHz)
6. **Twilio → 사용자**: 전화 음성

## 주요 설정

### VAD (Voice Activity Detection)

`app/services/openai_voice_client.py`에서 설정:

```python
"turn_detection": {
    "type": "server_vad",
    "threshold": 0.5,              # 음성 감지 민감도 (0.0-1.0)
    "prefix_padding_ms": 300,      # 음성 시작 전 포함할 시간
    "silence_duration_ms": 700     # 말이 끝났다고 판단하는 침묵 시간
}
```

### 시스템 프롬프트

`app/services/conversation_state.py`에서 수정:

```python
def build_system_prompt(self, stream_sid: str) -> str:
    base_prompt = (
        "You are a Korean-speaking customer service agent.\n"
        "You MUST respond in Korean language only.\n"
        # ... 추가 지침
    )
    return base_prompt
```

## 트러블슈팅

### 음성이 들리지 않는 경우

1. **로그 확인**: `tail -f server.log`
2. **오디오 전송 확인**: "✅ 오디오 청크 전송 완료" 로그 확인
3. **VAD 설정 확인**: `turn_detection`이 올바르게 설정되었는지 확인
4. **API 키 확인**: OpenAI API 키가 Realtime API 접근 권한이 있는지 확인

### 한국어가 아닌 다른 언어로 응답하는 경우

1. **시스템 프롬프트 확인**: `conversation_state.py`의 프롬프트 확인
2. **Voice 설정 확인**: `alloy` voice가 설정되어 있는지 확인
3. **세션 설정 확인**: `session.update` 메시지가 제대로 전송되는지 로그 확인

### `input_audio_buffer_commit_empty` 에러

- **원인**: 수동으로 `commit` 메시지를 보내고 있음
- **해결**: VAD 활성화 시 수동 커밋 제거 (현재 코드는 이미 수정됨)

## 테스트

```bash
# 전체 테스트 실행
pytest

# 특정 테스트 실행
pytest tests/test_audio.py

# 커버리지 확인
pytest --cov=app tests/
```

## 배포 체크리스트

- [ ] `.env` 파일 설정 완료 (프로덕션 키 사용)
- [ ] Twilio Voice Webhook URL 설정: `https://your-domain.com/twilio/voice`
- [ ] Twilio Media Stream WebSocket 설정: `wss://your-domain.com/twilio/stream`
- [ ] OpenAI Realtime API 접근 권한 확인 (Tier 1 이상)
- [ ] OpenAI 계정 결제 수단 등록 및 크레딧 충전
- [ ] TLS/SSL 인증서 설정 (WebSocket은 wss:// 필수)
- [ ] 서버 방화벽에서 포트 8080 (또는 사용 포트) 허용
- [ ] 로그 수집 및 모니터링 구성
- [ ] 에러 알림 설정 (Sentry, CloudWatch 등)

## 라이선스

MIT License

## 기여

이슈 및 PR은 언제든지 환영합니다!


