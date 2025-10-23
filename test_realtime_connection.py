"""
OpenAI Realtime API 연결 테스트 스크립트
"""
import asyncio
import os
import websockets
import json

async def test_realtime_connection():
    """OpenAI Realtime API 연결을 테스트합니다."""
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
        return
    
    # 테스트할 모델명 목록
    models_to_test = [
        "gpt-realtime",
        "gpt-4o-realtime-preview",
        "gpt-4o-realtime-preview-2024-10-01",
        "gpt-4o-realtime-preview-2024-12-17",
    ]
    
    for model_name in models_to_test:
        print(f"\n🔍 테스트 중: {model_name}")
        
        realtime_url = f"wss://api.openai.com/v1/realtime?model={model_name}"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        
        try:
            # 5초 타임아웃으로 연결 시도
            websocket = await asyncio.wait_for(
                websockets.connect(realtime_url, extra_headers=headers, max_size=None),
                timeout=5.0
            )
            
            print(f"✅ 연결 성공! 모델: {model_name}")
            
            # 세션 업데이트 메시지 전송
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "voice": "alloy",
                }
            }
            await websocket.send(json.dumps(session_update))
            print(f"   📤 세션 업데이트 전송 완료")
            
            # 응답 대기 (최대 3초)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                data = json.loads(response)
                print(f"   📥 응답 수신: {data.get('type')}")
                
                if data.get("type") == "error":
                    print(f"   ❌ 에러: {data.get('error')}")
                else:
                    print(f"   ✅ 정상 응답")
                    
            except asyncio.TimeoutError:
                print(f"   ⚠️ 응답 타임아웃 (하지만 연결은 성공)")
            
            await websocket.close()
            print(f"   🔒 연결 종료")
            
            # 성공한 모델을 찾았으면 종료
            print(f"\n🎉 사용 가능한 모델: {model_name}")
            break
            
        except asyncio.TimeoutError:
            print(f"   ❌ 연결 타임아웃 (5초)")
        except websockets.exceptions.InvalidStatusCode as e:
            print(f"   ❌ HTTP 에러: {e.status_code}")
        except Exception as e:
            print(f"   ❌ 연결 실패: {type(e).__name__}: {e}")
    else:
        print(f"\n❌ 모든 모델 연결 실패")
        print(f"\n💡 확인사항:")
        print(f"   1. API 키가 유효한지 확인")
        print(f"   2. 결제 수단이 등록되었는지 확인")
        print(f"   3. OpenAI Platform에서 Realtime API 사용 권한 확인")

if __name__ == "__main__":
    asyncio.run(test_realtime_connection())

