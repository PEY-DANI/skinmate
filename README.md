# SkinMate 🧴

이전 대화 기억·문서·관계 그래프를 컨텍스트로 맞춤형 화장품(성분/제품)을 추천하는 대화형 AI 시스템

> **상태**: 요구사항·아키텍처 확정 완료 (Deep Interview ambiguity 15% PASSED → 합의 플랜 pending approval). 구현 착수 전 게이트 3건 남음.

## 프로젝트 개요

**목표**: 로그인한 여러 사용자가 각자 개인화된 대화형 화장품 추천을 받는다. 시스템은 세 가지 컨텍스트 소스를 결합한다.

1. **문서(Documents/RAG)** — 성분·제품 문서를 pgvector 임베딩으로 저장·유사도 검색 (전역 공유)
2. **기억(Memory)** — LLM이 중요 사실만 선별해 관리, 빈도·최근성 가중치로 우선순위화 (사용자별 격리)
3. **관계 그래프(Graph)** — Apache AGE로 엔티티+연결동사 저장, 다단계 추론 (사용자별 격리)

추천은 **다중 턴 대화 퍼널** — 성분/카테고리 조언에서 시작해 대화로 좁혀 최종적으로 구체 제품명 + 근거까지 제시한다. 핵심 추론은 그래프 다단계 순회(예: 민감성 → 성분 회피 → 해당 성분 포함 제품 제외 → 대체 성분 추천).

## 기술 스택

- **DB**: PostgreSQL 단일 인스턴스 + `age`(그래프) + `vector`(pgvector 임베딩) 확장 공존
- **기억 파이프라인**: 응답 직후 **비동기 워커**(작업 큐) — fact 추출 → 유사도 매칭 → LLM CRUD 판단 → 가중치/모순 재정리
- **LLM**: 프로바이더 추상화 (기본 Claude API, 교체 가능)
- **임베딩**: 다국어 모델(KO + INCI-EN), 문서/기억 임베딩 공간 분리, 차원 DDL 고정

## 핵심 설계 결정

### 기억 관리 (Memory CRUD)
LLM이 중요 사실 여부를 판단해:
- **신규 사실 → add**
- **기존 사실의 값 변경 → update** (같은 슬롯, 새 값으로 덮어쓰기) — 예: `피부타입 건성 → 복합성`, `선호 제형 로션 → 크림`. 사실은 유지되고 값만 갱신.
- **사실 철회/무효 → delete** (같은 슬롯에 대체 값 없이 사실 자체가 더 이상 성립 안 함) — 예: "임신 중이라 레티놀 회피" → "출산함"(회피 제약 소멸), "A 성분 알러지 있음" → "검사결과 아니었음"(사실이 거짓)
- **중복 사실 → no-op**
- 일상/사소 정보(예: "오늘 피곤해")는 저장하지 않음 (delete는 soft-delete + 감사로그로 잘못된 삭제 방지)

> **update vs delete 핵심**: 같은 속성의 값이 바뀌면 update, 사실 자체가 대체값 없이 사라지면 delete.

### 가중치 (사람다운 중요도)
```
effective_weight = weight × exp(-λ × days_since_last_seen)      (λ = 0.02 기본값)
```
자주·최근 언급될수록 검색 상위. `weight`는 언급 빈도로 증가, 지수 시간감쇠(half-life ≈ 35일)로 최근성 반영.

### 그래프 스키마 (하이브리드)
- **코어 노드**: User, Product, Ingredient, Concern, SkinType (고정)
- **코어 엣지**: CONTAINS, TREATS, AVOIDS, PREFERS, HAS_CONCERN (고정)
- LLM이 새 관계 제안 시 승인 후 점진 확장

### 사용자 격리 (하드 불변식)
- `memories` 등 관계형 데이터 → PostgreSQL RLS
- AGE 서브그래프 → RLS 적용 불가하므로 **choke-point 함수**가 `user_scope` 필터 강제 + 크로스유저 누수 0건 테스트

## 데이터 수집

- **주 소스(계획)**: [coos.kr/ingredients](https://coos.kr/ingredients) 크롤링 (한글 성분 사전)
- ⚠️ **현재 보류** — 빌드 전 `robots.txt`·이용약관 확인 게이트 통과 필요. 불허 시 공개 소스(CosIng / Open Beauty Facts / 식약처·공공데이터포털)로 승격.
- 조인 키: INCI 영문명 canonical, 없으면 한글 성분명. rate-limit + 캐시 + 출처·수집일시 메타.

## 문서

- 📋 [요구사항 스펙 (Deep Interview)](deep-interview-cosmetics-recommendation-memory-graph.md) — 토폴로지, 목표, 제약, 수용 기준 16개, 온톨로지, 인터뷰 트랜스크립트
- 📐 [합의 플랜 (Consensus Plan)](cosmetics-recommendation-consensus-plan.md) — 아키텍처, 데이터 모델, 구현 단계, 리스크, ADR (Architect + Critic 검토 반영)

## 착수 전 게이트 (빌드 시작 전 확정 필요)

1. **임베딩 모델·차원** 확정 (되돌리기 어려움 — multilingual-e5 / BGE-m3 계열 후보 벤치 후 고정)
2. **coos.kr 법적 허용 여부** 확인 (불허 시 공개 소스 폴백)
3. **목표 데이터 규모** 실측 (AGE 다단계 순회 p95<300ms 게이팅 벤치마크 기준)

---
**Created**: 2026-07-02 · **Updated**: 2026-07-02
**다음 단계**: 실행(team/ralph/autopilot)은 별도 승인 필요 — 현재 자동 시작 안 함
