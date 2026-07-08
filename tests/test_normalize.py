"""성분 정규화 모듈 normalize.py 에 대한 단위 테스트 (WBS 1A.1)."""

from __future__ import annotations

from ingest.normalize import create_canonical_key


def test_create_canonical_key_with_english_name() -> None:
    """영문명이 주어진 경우 영문명 기준 정규화가 수행되는지 검증합니다."""
    # 소문자화 및 특수문자 언더스코어 치환
    key1 = create_canonical_key(
        "Almond/Borage/Linseed/Olive Acids/Glycerides*",
        "(아몬드/보리지/아마/올리브)애씨드/글리세라이즈",
    )
    assert key1 == "almond_borage_linseed_olive_acids_glycerides"

    # 일반적인 복합 성분
    key2 = create_canonical_key("Ascorbyl Glucoside", "아스코빌글루코사이드")
    assert key2 == "ascorbyl_glucoside"


def test_create_canonical_key_with_ko_only() -> None:
    """영문명이 없는 경우 한글명을 기반으로 정규화가 동작하는지 검증합니다."""
    # 괄호 제거 규칙
    key1 = create_canonical_key(None, "소듐하이알루로네이트 (히알루론산)")
    assert key1 == "소듐하이알루로네이트"

    # 단순 한글
    key2 = create_canonical_key(None, "정제수")
    assert key2 == "정제수"

    # 다중 구분자 정제
    key3 = create_canonical_key(None, "돌콩 오일 - 추출물,")
    assert key3 == "돌콩_오일_추출물"
