# retrieval — 담당: A (동기 읽기 경로)

pgvector 유사도 + AGE 다단계 순회 + 기억 순위 → 통합 컨텍스트(ContextBundle, 계약 1).

- WBS: A3.1~A3.5 (AC-G1~G2, AC-M2)
- 지연 예산: p95 < 300ms (미달 시 materialized-adjacency 폴백, A3.4 ★)
- 사용자 그래프 접근은 반드시 검문소 함수(A1.2) 경유
- 기억 순위 계산은 B의 memory_rank(B2.5) 호출
