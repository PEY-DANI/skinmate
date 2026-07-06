# contracts — 담당: 공동 ★

두 작업자의 코드가 만나는 인터페이스 계약. **이 디렉터리의 변경은 상대방 리뷰 필수.**

| 계약 | 방향 | 내용 |
|---|---|---|
| 1. ContextBundle | A→B | `retrieve(user_id, query) → { documents, graph_paths, memories }` |
| 2. MemoryWriteJob | B→큐 | 기억 저장 잡 스키마(user_id, turn_id, 대화 버퍼) + `pending_writes_drained(user_id)` |
| 3. 그래프 검문소 | A제공/B소비 | 사용자 서브그래프 접근은 `query_user_graph(user_id, ...)` 단일 함수만 — 직접 Cypher 금지 |

- WBS: 0.5 ★ — 계약 확정 시 fixture(가짜 데이터)도 함께 커밋
- Phase 1 동안 계약별 contract test를 CI에 추가 예정
