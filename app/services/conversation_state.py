"""콜 세션별 대화 상태와 지시문을 관리합니다."""

from typing import Dict


class ConversationStateManager:
    """콜 세션별로 컨텍스트와 시스템 프롬프트를 제공합니다."""

    def __init__(self) -> None:
        self._session_context: Dict[str, Dict[str, str]] = {}

    def build_system_prompt(self, stream_sid: str) -> str:
        """콜 세션을 위한 시스템 프롬프트를 생성합니다."""

        session_data = self._session_context.setdefault(stream_sid, {})
        base_prompt = (
            "You are a Korean-speaking customer service agent.\n"
            "You MUST respond in Korean language only.\n"
            "\n"
            "Example conversation:\n"
            "Customer: 여보세요?\n"
            "You: 안녕하십니까. 무엇을 도와드릴까요?\n"
            "Customer: 예약 확인하고 싶어요.\n"
            "You: 네, 예약 확인 도와드리겠습니다.\n"
            "\n"
            "Always respond in Korean like the examples above."
        )
        custom_context = session_data.get("context", "")
        return f"{base_prompt}\n{custom_context}".strip()

    def update_context(self, stream_sid: str, key: str, value: str) -> None:
        """대화 중 누적 정보를 저장합니다."""

        session_data = self._session_context.setdefault(stream_sid, {})
        session_data[key] = value

    def pop_context(self, stream_sid: str, key: str, default: str = "") -> str:
        """세션 컨텍스트에서 값을 가져오고 삭제합니다."""

        session_data = self._session_context.setdefault(stream_sid, {})
        return session_data.pop(key, default)

    def clear(self, stream_sid: str) -> None:
        """콜 종료 시 세션 정보를 정리합니다."""

        self._session_context.pop(stream_sid, None)


