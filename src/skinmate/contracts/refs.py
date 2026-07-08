"""성분·제품 경량 참조 계약 — 트랙 A↔B 가 주고받는 핸들(⭐7).

근거: docs/DATA-MODEL.md §1(ingredients·products), db/migrations/001_core_knowledge.sql.
전체 행이 아니라 식별·표기에 필요한 최소 필드만 담는다.
"""

from __future__ import annotations

from pydantic import BaseModel


class IngredientRef(BaseModel):
    """성분 참조. canonical_key(INCI 우선, 없으면 정규화 한글명)가 병합·다리 해석의 열쇠."""

    ingredient_id: int
    canonical_key: str
    name_ko: str | None = None
    name_en: str | None = None
    inci_key: str | None = None


class ProductRef(BaseModel):
    """제품 참조. RetrievalContext 의 후보 제품을 담는 최소 핸들."""

    product_id: int
    name: str
    brand: str | None = None
