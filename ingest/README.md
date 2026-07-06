# ingest — 담당: A

배치 ETL: coos.kr 크롤링 → 정규화/중복제거 → 임베딩 적재 → AGE 그래프 엣지 구축.

- WBS: A2.1~A2.5 (AC-D1~D3)
- 크롤링 전 robots.txt/약관 확인(0.4 게이트), rate-limit 1~2 req/s, 캐시, 출처·수집일시 메타 필수
