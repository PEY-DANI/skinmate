"""라우팅(1B.6) — 발화를 정보진술/추천-구체/추천-모호 로 분류한다(PRD F6, AC-R1).

판정은 "LLM + 규칙"이다: LLM 은 의도와 구체 슬롯(고민/제형/성분/브랜드 언급 여부)만 구조화
추출하고, "슬롯이 하나라도 있으면 구체"라는 최종 임계치 판단은 코드가 결정적으로 한다 —
LLM 이 매번 다른 기준으로 구체/모호를 흔들리게 판단하지 않도록 함(CRUD 판정과 같은 설계 원칙).
파싱 실패 2회면 **VAGUE 로 안전 폴백**(모른다고 억지로 추천하지 않고 좁히기 질문으로 전환).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import structlog
from pydantic import BaseModel

from skinmate.errors import LLMError
from skinmate.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

_PROMPT = (
    Path(__file__).resolve().parent.parent / "llm" / "prompts" / "classify_route.txt"
).read_text(encoding="utf-8")

_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["statement", "recommendation"]},
        "has_concern_slot": {"type": "boolean"},
        "has_texture_slot": {"type": "boolean"},
        "has_ingredient_slot": {"type": "boolean"},
        "has_brand_slot": {"type": "boolean"},
    },
    "required": ["intent"],
}

_SLOT_KEYS = {
    "concern": "has_concern_slot",
    "texture": "has_texture_slot",
    "ingredient": "has_ingredient_slot",
    "brand": "has_brand_slot",
}


class Route(StrEnum):
    """대화 라우팅 결과(PRD F6). STATEMENT 는 추천 흐름을 타지 않는다."""

    STATEMENT = "statement"
    SPECIFIC = "specific"
    VAGUE = "vague"


class RouteDecision(BaseModel):
    """라우팅 결과 + 이 발화에서 감지된 구체 슬롯(퍼널이 known_slots 계산에 재사용)."""

    route: Route
    concern: bool = False
    texture: bool = False
    ingredient: bool = False
    brand: bool = False

    def known_slots(self) -> set[str]:
        """이 발화에서 참(True)인 슬롯 이름 집합."""
        values = {
            "concern": self.concern,
            "texture": self.texture,
            "ingredient": self.ingredient,
            "brand": self.brand,
        }
        return {name for name, present in values.items() if present}


def _build_prompt(utterance: str, history: list[str] | None) -> str:
    history_text = "\n".join(history) if history else "(없음)"
    return f"[직전 대화]\n{history_text}\n\n[현재 발화]\n{utterance}"


def classify_route(
    provider: LLMProvider, utterance: str, *, history: list[str] | None = None
) -> RouteDecision:
    """발화를 라우팅한다. history 는 짧은 후속 답변("건조요" 등)의 맥락 해석에 쓰인다."""
    prompt = _build_prompt(utterance, history)
    for attempt in (1, 2):
        try:
            raw = provider.complete_json(_PROMPT, prompt, _SCHEMA)
            return _parse(raw)
        except (LLMError, ValueError) as exc:
            logger.warning("route_classify_retry", attempt=attempt, error=str(exc))
    logger.error("route_classify_gave_up", utterance=utterance)
    return RouteDecision(route=Route.VAGUE)


def _parse(raw: dict[str, object]) -> RouteDecision:
    intent = raw.get("intent")
    slots = {name: bool(raw.get(key, False)) for name, key in _SLOT_KEYS.items()}

    if intent == "statement":
        return RouteDecision(route=Route.STATEMENT, **slots)
    if intent == "recommendation":
        is_specific = any(slots.values())
        return RouteDecision(route=Route.SPECIFIC if is_specific else Route.VAGUE, **slots)
    raise ValueError(f"알 수 없는 intent: {intent!r}")
