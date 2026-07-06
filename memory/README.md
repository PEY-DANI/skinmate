# memory — 담당: B (비동기 쓰기 경로)

턴 종료 후 백그라운드 기억 파이프라인: fact 추출 → CRUD 판정(add/update/delete/no-op) → 가중치 재계산.

- WBS: B2.1~B2.6 (AC-M1~M6)
- 큐는 user_id 직렬화 + idempotency-key + dead-letter, delete는 soft-delete+감사로그
- `pending_writes_drained(user_id)` 제공 (계약 2) — retrieval이 읽기 전 호출
