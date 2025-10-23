"""
OpenAI Realtime API 테스트 스크립트
세션 생성 및 기본 응답 테스트
"""
import asyncio
import json
import os
import sys
import base64

import httpx
import websockets


async def test_realtime_api():
    """OpenAI Realtime API 기본 기능 테스트"""
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
        sys.exit(1)
    
    print("=" * 60)
    print("OpenAI Realtime API 테스트 시작")
    print("=" * 60)
    
    # 1단계: 세션 생성
    print("\n[1단계] 세션 생성 중...")
    
    session_payload = {
        "model": "gpt-realtime",
        "modalities": ["text", "audio"],
        "voice": "alloy",
        "instructions": "당신은 친절한 AI 어시스턴트입니다. 간결하게 답변하세요.",
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
        },
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "realtime=v1",
        }
        
        try:
            response = await client.post(
                "https://api.openai.com/v1/realtime/sessions",
                headers=headers,
                json=session_payload,
            )
            response.raise_for_status()
            session_data = response.json()
            
            print(f"✅ 세션 생성 성공")
            print(f"   - Session ID: {session_data.get('id')}")
            print(f"   - Model: {session_data.get('model')}")
            print(f"   - Expires At: {session_data.get('expires_at')}")
            
            client_secret = session_data["client_secret"]["value"]
            
        except httpx.HTTPStatusError as e:
            print(f"❌ 세션 생성 실패: {e.response.status_code}")
            print(f"   응답: {e.response.text}")
            sys.exit(1)
    
    # 2단계: WebSocket 연결
    print("\n[2단계] WebSocket 연결 중...")
    
    realtime_url = f"wss://api.openai.com/v1/realtime?model=gpt-realtime"
    ws_headers = {
        "Authorization": f"Bearer {client_secret}",
        "OpenAI-Beta": "realtime=v1",
    }
    
    try:
        async with websockets.connect(realtime_url, extra_headers=ws_headers, max_size=None) as websocket:
            print("✅ WebSocket 연결 성공")
            
            # 3단계: 세션 설정 업데이트 (WebSocket을 통해)
            print("\n[3단계] 세션 설정 업데이트 중...")
            
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "voice": "alloy",
                    "instructions": "당신은 친절한 AI 어시스턴트입니다. 간결하게 답변하세요.",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500,
                    },
                }
            }
            
            await websocket.send(json.dumps(session_update))
            print("✅ 세션 설정 업데이트 전송")
            
            # 4단계: 더미 오디오 전송 및 초기 인사 요청
            print("\n[4단계] 더미 오디오 전송 및 초기 인사 요청 중...")
            
            # 더미 오디오 생성 (200ms 분량의 침묵)
            # PCM16, 16kHz, mono = 16000 samples/sec * 0.2 sec * 2 bytes = 6400 bytes
            samples = 3200  # 200ms
            silence_audio = b'\x00\x00' * samples
            silence_b64 = base64.b64encode(silence_audio).decode('ascii')
            
            # 오디오 버퍼에 추가
            append_audio = {
                "type": "input_audio_buffer.append",
                "audio": silence_b64,
            }
            await websocket.send(json.dumps(append_audio))
            print("✅ 더미 오디오 전송 (200ms 침묵)")
            
            # 오디오 버퍼 커밋
            commit_audio = {
                "type": "input_audio_buffer.commit"
            }
            await websocket.send(json.dumps(commit_audio))
            print("✅ 오디오 버퍼 커밋")
            
            # 짧은 대기 (VAD가 처리할 시간)
            await asyncio.sleep(0.1)
            
            # 응답 생성 요청
            response_request = {
                "type": "response.create",
                "response": {
                    "modalities": ["audio", "text"],
                    "instructions": "'안녕하십니까. 무엇을 도와드릴까요?'라고 간단하게 인사하세요.",
                }
            }
            await websocket.send(json.dumps(response_request))
            print("✅ 응답 생성 요청 전송")
            
            # 5단계: 응답 수신
            print("\n[5단계] 응답 수신 중...\n")
            
            audio_deltas_received = 0
            text_received = ""
            timeout = 10  # 10초 타임아웃
            
            try:
                async with asyncio.timeout(timeout):
                    async for message in websocket:
                        try:
                            payload = json.loads(message)
                            event_type = payload.get("type")
                            
                            if event_type == "session.updated":
                                print(f"📋 세션 업데이트됨")
                                session_info = payload.get("session", {})
                                print(f"   - Modalities: {session_info.get('modalities')}")
                                print(f"   - Voice: {session_info.get('voice')}")
                                print(f"   - Output Audio Format: {session_info.get('output_audio_format')}")
                                
                            elif event_type == "response.created":
                                print(f"🎬 응답 생성 시작")
                                
                            elif event_type == "response.output_audio.delta":
                                audio_deltas_received += 1
                                delta_size = len(payload.get("delta", ""))
                                if audio_deltas_received == 1:
                                    print(f"🎵 오디오 델타 수신 시작!")
                                if audio_deltas_received % 10 == 0:
                                    print(f"   - {audio_deltas_received}개 청크 수신 중... (최근 크기: {delta_size} bytes)")
                                    
                            elif event_type == "response.audio_transcript.delta":
                                text_received += payload.get("delta", "")
                                
                            elif event_type == "response.done":
                                print(f"\n✅ 응답 완료")
                                print(f"   - 오디오 델타 수신: {audio_deltas_received}개")
                                print(f"   - 텍스트 트랜스크립트: {text_received}")
                                
                                response_data = payload.get("response", {})
                                print(f"   - Status: {response_data.get('status')}")
                                print(f"   - Output: {json.dumps(response_data.get('output'), indent=4, ensure_ascii=False)}")
                                
                                break
                                
                            elif event_type == "error":
                                error_info = payload.get("error", {})
                                print(f"❌ 오류 발생: {error_info.get('code')}")
                                print(f"   메시지: {error_info.get('message')}")
                                
                        except json.JSONDecodeError:
                            print("⚠️  JSON 파싱 실패")
                            
            except asyncio.TimeoutError:
                print(f"\n⏱️  타임아웃 ({timeout}초)")
            
            # 결과 요약
            print("\n" + "=" * 60)
            print("테스트 결과 요약")
            print("=" * 60)
            
            if audio_deltas_received > 0:
                print(f"✅ 오디오 출력: 성공 ({audio_deltas_received}개 청크)")
            else:
                print(f"❌ 오디오 출력: 실패 (0개 청크)")
                print(f"   → OpenAI가 오디오를 생성하지 않았습니다.")
                print(f"   → 세션 설정 또는 모달리티 문제일 가능성이 높습니다.")
            
            if text_received:
                print(f"✅ 텍스트 출력: 성공")
                print(f"   내용: \"{text_received}\"")
            else:
                print(f"⚠️  텍스트 출력: 없음")
            
    except Exception as e:
        print(f"❌ WebSocket 연결 실패: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_realtime_api())

