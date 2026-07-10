"""라우팅 테스트 — 의도·구체슬롯 파싱, "슬롯 하나라도 있으면 구체" 규칙, 폴백(AC-R1).

가짜 프로바이더로 LLM 출력을 고정해 규칙(코드) 부분만 결정적으로 검증한다. DB 불필요.
"""

from __future__ import annotations

from skinmate.chat.route import Route, classify_route
from skinmate.errors import LLMError


class _CannedProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def complete(self, system: str, prompt: str) -> str:
        return ""

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, object]
    ) -> dict[str, object]:
        return self._payload


class _FlakyProvider:
    def __init__(self, fail_times: int, payload: dict[str, object]) -> None:
        self._fail_times = fail_times
        self._payload = payload
        self.calls = 0

    def complete(self, system: str, prompt: str) -> str:
        return ""

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, object]
    ) -> dict[str, object]:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise LLMError("모의 실패")
        return self._payload


def test_statement_intent_routes_to_statement() -> None:
    provider = _CannedProvider({"intent": "statement", "has_concern_slot": True})
    decision = classify_route(provider, "저는 레티놀 쓰면 자극나요")
    assert decision.route == Route.STATEMENT


def test_recommendation_with_slot_is_specific() -> None:
    provider = _CannedProvider(
        {"intent": "recommendation", "has_texture_slot": True, "has_concern_slot": True}
    )
    decision = classify_route(provider, "에멀전으로 건조에 좋은 거 추천해줘")
    assert decision.route == Route.SPECIFIC
    assert decision.known_slots() == {"texture", "concern"}


def test_recommendation_without_any_slot_is_vague() -> None:
    provider = _CannedProvider({"intent": "recommendation"})
    decision = classify_route(provider, "요즘 피부가 별로인데 뭐 쓰면 좋을까?")
    assert decision.route == Route.VAGUE
    assert decision.known_slots() == set()


def test_unknown_intent_retries_then_falls_back_to_vague() -> None:
    provider = _CannedProvider({"intent": "chit-chat"})
    decision = classify_route(provider, "아무거나")
    assert decision.route == Route.VAGUE


def test_llm_error_retries_then_recovers() -> None:
    provider = _FlakyProvider(fail_times=1, payload={"intent": "statement"})
    decision = classify_route(provider, "저는 지성이에요")
    assert decision.route == Route.STATEMENT
    assert provider.calls == 2


def test_llm_error_gives_up_after_two_falls_back_to_vague() -> None:
    provider = _FlakyProvider(fail_times=2, payload={"intent": "statement"})
    decision = classify_route(provider, "아무거나")
    assert decision.route == Route.VAGUE
    assert provider.calls == 2
