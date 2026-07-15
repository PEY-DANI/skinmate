# 그래프 한글 canonical_key 마이그레이션 (Phase 2)

작업자 A 합의용 요약 문서. 워킹 트리 변경만 있으며 아직 commit/push 되지 않았다.

## 1. 문제 · 원인

- `ingredients.canonical_key`(UNIQUE) 389개 행이 한글로 저장돼 있었다. 원인은
  `ingest/normalize.py` 가 제품 성분표에서 성분명(name_ko)을 해석하지 못하면 한글
  canonical_key 로 신규 `ingredients` 행을 INSERT 해왔기 때문이다(근본 원인 — 이번
  작업에서는 건드리지 않음, §4 참고).
- `product_ingredients` 1,102건 중 1,098건이 이 한글 키 행을 참조하고 있었다.
- `src/skinmate/graph/knowledge_populate.py` 가 그래프 투영 시
  `re.sub(r"[^a-z0-9_]+", "", key.lower())` 로 canonical_key 를 "정제"했는데, 한글은
  전부 삭제되는 문자라 한글 키가 `"_200"`, `"4_t_"` 같은 서로 다른 한글 키들이 같은
  깨진 문자열로 뭉개져 충돌했다. 그 결과:
  - CONTAINS 엣지 1,098개가 전부 이 깨진 노드들에 잘못 MERGE 되어, 실제로는 정상
    엣지가 134개밖에 남아있지 않았다(정상치는 1,000대여야 함).
  - populate 는 MERGE 기반 멱등 스크립트라 재실행해도 이미 만들어진 깨진 노드는
    지워지지 않고 계속 쌓였다.

## 2. `knowledge_populate.py` 변경점과 이유

1. 상단에 `_VALID_KEY_RE = re.compile(r"^[a-z0-9_]+$")` 추가.
2. Ingredient(§2) / CONTAINS(§4) / TREATS·AGGRAVATES(§5) / AVOIDS(§7나) / PREFERS(§7다)
   5개 지점의 `re.sub` 파괴적 정제를 전부 제거하고, `_VALID_KEY_RE.match()` 실패 시
   **해당 항목만 skip** 하도록 바꿨다. 문자를 삭제·변형하지 않으므로 더 이상 서로
   다른 한글 키가 같은 값으로 뭉개지지 않는다. 각 섹션별로 skip 카운터를 두고
   함수 말미에 0이 아니면 `invalid_canonical_key_skipped` 경고 로그로 집계 출력한다.
3. HAS_CONCERN(§7라) 엣지 생성 로직을 복구했다. `memories.target_name` 은 두 가지
   형태로 저장될 수 있다 — CONCERN_RULES 의 영문 키 그대로(`'dryness'`, 그래프 직접
   기록 케이스) 또는 한글 라벨(`'건조'`, LLM 이 자연어로 채운 케이스). 처리 순서:
   ① `target_name.lower()` 가 CONCERN_RULES 키와 정확히 일치하면 그대로 사용
   ② 아니면 라벨→키 역방향 dict(`{rule["label"]: name for ...}`)로 변환
   ③ 둘 다 실패하면 skip + 카운터(`has_concern_resolution_skipped`).
   `tests/graph/test_traverse.py`(영문 `'dryness'`)와 `tests/app/test_turn.py`(한글
   `'건조'`) 두 형태 모두 이 로직 하나로 통과한다.
4. `ingest/`, `graph/traverse.py`, `graph/choke.py` 는 수정하지 않았다(스펙 제약).

## 3. 마이그레이션(`scripts/migrate_korean_canonical_keys.py`) 실행 결과

### 3-1. 분류 (dry-run)

| 분류 | 행 수 | product_ingredients 매핑 수 |
|---|---|---|
| 단일 후보(자동 병합 대상) | 338 | 951 |
| 모호(복수 후보, 리포트-온리) | 21 | 111 |
| 후보 없음(리포트-온리) | 30 | 36 |
| 합계 | 389 | 1,098 |

### 3-2. `--apply` 결과

- `rows_processed=338`, `product_ingredients_repointed=951`,
  `product_ingredients_deduped=0`, `memories_repointed=0`.
- dedup 0건 — 같은 제품이 한글 행과 영문 행을 동시에 이미 참조하던 케이스는 없었음.
- memories 0건 — `memories.target_ingredient_id` 가 한글 키 행을 참조하던 사례는
  마이그레이션 전부터 0건이었음(FK 는 이 컬럼과 `product_ingredients.ingredient_id`
  둘뿐).
- **모호 21건 미포함 검증**: apply 전/후로 모호 21행의 매핑 수(111건)가 그대로임을
  확인함 — `_apply()` 는 단일 후보(single) 리스트만 순회하므로 설계상 건드릴 수 없다.
- **멱등성 검증**: `--apply` 를 연속으로 두 번째 실행하면
  `product_ingredients_repointed=0`, `deduped=0`, `memories_repointed=0` — 변경 0건.
- apply 이후 한글 키를 참조하는 `product_ingredients` 잔존 건수: 147건
  (모호 111 + 후보없음 36, dry-run 수치와 정확히 일치).
- 한글 `ingredients` 행 389개 자체는 삭제하지 않았다(정책대로 보존, §4 결정 필요).

### 3-3. `populate_graph.py` 재실행 + `--clean-graph` 결과

- populate 재실행: `invalid_canonical_key_skipped` — `ingredient=389, contains=147,
  treats_aggravates=389, avoids=0, prefers=0, total=925`(전부 남아있는 한글 키 행에서
  기인, 파괴적 정제가 사라졌으므로 예상된 정상 동작). `has_concern_resolution_skipped`
  로그는 찍히지 않음(현재 데이터의 모든 HAS_CONCERN 이 정상 해석됨).
- `--clean-graph`: 그래프 Ingredient 노드(2,576개) vs RDB canonical_key 전체집합
  (2,925개)을 차집합해 RDB 에 없는 순수 잔재 키 40개(`"_200"`, `"4_t_"`,
  `"c12_15"` 등 과거 파괴적 정제가 만든 깨진 값들)를 개별 DETACH DELETE.
  한글 키 자체는 RDB 에 여전히 존재하므로 이 단계에서 지워지지 않는다(의도된 동작,
  스크립트 독스트링에 명시).

### 3-4. 그래프 검증(최종 상태)

- CONTAINS 총수: **955**(1,000대는 아니지만, populate 시점에 RDB 상 유효(ASCII) 키로
  이미 재연결된 매핑 수 955건과 정확히 일치 — 나머지 147건은 §3-1 의 모호/후보없음
  잔존분이라 의도된 결과. "복원 실패"가 아니라 "정상 데이터만 반영"된 것).
- RDB 에 없는 키의 Ingredient 노드: **0개**(clean-graph 후 rdb_keys=graph_keys 차집합
  재확인 완료, `_200` 등 잔재 완전 소멸).
- 그래프 Ingredient 노드 수(2,536) = RDB 유효 키(`^[a-z0-9_]+$`) 행 수(2,536) — **정확히
  일치**.
- 핵심 E2E(`sensitivity`/`dryness` 등 일반 조회): 2-hop
  `Product-CONTAINS->Ingredient-TREATS->Concern` 경로가 다수 확인됨(예:
  `dryness`/`c12_15_alkyl_benzoate`/상품 여러 건).
  ⚠️ 스펙에 명시된 특정 쿼리(`user_id=500833236`, 고민='트러블'/acne)는 **0행**이었다
  — 원인은 그래프 버그가 아니라 **카탈로그 데이터 부족**: 현재 41개 제품 중 acne 를
  TREATS 하는 성분(`benzoyl_peroxide` 등 7종)을 포함하는 제품이 하나도 없다
  (`product_ingredients` 레벨에서 확인, RDB 사실). `dryness`/`sensitivity` 고민으로
  같은 쿼리를 돌리면 정상적으로 행이 나온다. 이 문제는 그래프 엔진/마이그레이션과
  무관하며 카탈로그 확장이 필요한 별도 이슈로 A 공유 필요.
- VLE 회귀(`MATCH p = (u:User {user_id: 500833236})-[*1..3]->(x) ...`): 에러 없이
  동작(HAS_CONCERN→Concern 1-hop 경로 정상 반환).
- 개인 엣지 vs `memories` 기대치: HAS_CONCERN 3/3(전부 정상 해석, 영문·한글 두 형태
  모두 포함), AVOIDS 1(memories 2건 중 1건은 `target_ingredient_id` 가 애초에
  NULL — 성분 해석 실패로 텍스트만 보존된 pre-existing 케이스, 이번 작업 범위 밖),
  PREFERS 2(memories 3건 중 동일 사유로 1건 NULL) — 전부 예상과 일치.

## 4. A 결정 필요 항목

1. **모호 21건 수동 판정**: 위 §3-1 표의 21행은 같은 name_ko 에 영문 후보가 2~3개씩
   있어 자동 병합하지 않았다. 후보 상세(ingredient_id/canonical_key/inci_key)는
   `.venv/Scripts/python.exe scripts/migrate_korean_canonical_keys.py` (dry-run, 기본
   실행)의 `ambiguous_candidate` 로그로 전체 확인 가능. 예: `정제수`(kor_id=2554)는
   `aqua_water_eau` / `water` / `purified_water` 3개 후보 중 하나를 골라야 함.
   결정 후 어떤 매핑을 쓸지 알려주면 스크립트에 예외 매핑 테이블을 추가하거나 개별
   SQL 로 반영 가능.
2. **후보없음 30행(매핑 36건) 처리 방안**: 위 §3-1 표 하단 목록 — 대부분 농도 표기가
   붙은 변형(`락틱애씨드(2.006%)`), 산화철 색소(적색/황색/흑색), 복합 표기(`피이지/
   피피지-18/18다이메티콘`) 등 성분사전에 정확히 대응하는 영문 행이 없는 경우다.
   (a) 성분사전에 신규 영문 행을 추가할지, (b) 한글 키 그대로 그래프에 노출할지(현재
   기본 동작 — RDB 에 남아있으므로 향후 memory bridge 가 자연스럽게 한글 키 노드를
   만들 수 있음), (c) 별도 정규화 규칙(괄호 안 농도 제거 등)을 추가할지 결정 필요.
3. **한글 행 389개 자체를 삭제할지 여부**: 이번 마이그레이션은 FK 만 재연결했고
   원본 한글 `ingredients` 행은 전부 보존했다(정책). 모호/후보없음 결정이 끝난
   뒤에도 여전히 참조되지 않는 한글 행이 남으면(자동 병합된 338개는 이제
   product_ingredients 에서 참조되지 않음) 삭제 여부를 정해야 한다.
4. **근본 원인 수정 별도 PR 필요**: `ingest/normalize.py` 가 name_ko 해석 실패 시
   한글 키로 신규 INSERT 하는 로직 자체는 이번 작업에서 건드리지 않았다. 이 마이그
   레이션은 1회성이므로, 근본 수정 없이는 다음 크롤링에서 같은 문제가 재발한다.
5. **카탈로그 데이터 부족(참고)**: §3-4 에서 발견한, acne(트러블) 고민을 해결하는
   제품이 카탈로그에 아예 없는 문제는 이번 작업 범위 밖이지만 제품 확장 시 고려
   바람.
