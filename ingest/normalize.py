"""성분명 정규화 및 INCI 매핑 유틸리티 (WBS 1A.1)."""

from __future__ import annotations

import re


def create_canonical_key(english_name: str | None, name_ko: str) -> str:
    """성분 영문명 혹은 한글명을 기준으로 정규화된 canonical_key를 생성합니다.

    규칙:
    - 소문자화
    - 끝의 * 등 비-단어 특수문자 제거
    - 공백, 하이픈 등 구분자는 언더스코어(_)로 단일화
    - 양끝의 언더스코어 제거
    """
    if english_name:
        key = english_name.lower().strip()
        # 끝에 붙은 별표(*) 등 특수문자 제거
        key = re.sub(r"\*+$", "", key)
        # 알파벳, 숫자, 언더스코어를 제외한 문자를 언더스코어로 변환
        key = re.sub(r"[^a-z0-9_]+", "_", key)
        key = key.strip("_")
        if key:
            return key

    # 한글명 정규화 폴백
    key = name_ko.strip()
    # 괄호 및 괄호 내부 내용 제거
    key = re.sub(r"\s*\(.*?\)\s*", "", key)
    # 한글, 알파벳, 숫자 이외의 문자를 언더스코어로 변환
    key = re.sub(r"[^가-힣a-zA-Z0-9]+", "_", key)
    key = key.strip("_")
    return key
