# Open Questions

## skinmate-consensus-plan - 2026-07-06 (updated post Architect/Critic consensus)

### Resolved (decided independently in the plan — NOT deferred to db/schema.sql, per fresh-start decision)
- [x] Embedding model + dimension (D_DOC) — **DECIDED: BAAI/bge-m3, 1024-dim, multilingual KO+EN.** One model for product prose + docs.
- [x] Ingredient embeddings (D_ING) — **DECIDED: NOT used in v1.** No AC requires ingredient-level vector similarity; structured columns + graph cover it.
- [x] λ starting value — **DECIDED: 0.05/day (~14-day half-life).** Tunable against AC-M2.
- [x] Embedding versioning — **DECIDED: store `embedding_model_id` per vector row; model swap = planned re-embed migration (R7).**

### Resolved (post-approval, 2026-07-06 — user decisions)
- [x] Primary crawl source(s) + ToS posture — **DECIDED: two pluggable sources — coos.kr (ingredient canonical + Korean names) + Paula's Choice Beautypedia / paulaschoice.co.kr (ingredient docs + product formulation prose).** No robots.txt → polite rate-limited cached crawl; ToS/copyright still apply (non-commercial; revisit before commercialization). Satisfies R6 (≥2 pluggable) + AC-D1 prose gate (Paula's Choice product pages).
- [x] Async worker technology — **DECIDED: NONE. Memory writes are SYNCHRONOUS.** Single-Postgres transaction does the atomic 3-store write inline; `write_jobs` queue/worker/drain/dead-letter removed. Single-Postgres already guarantees atomicity, so a queue only bought async delivery which v1 doesn't need. Promotable to async later behind `write/writer.py`.
- [x] Seasonal signal — **DECIDED: hand-curate the `season_concerns` seed** (~10–20 rows; no clean structured source). Satisfies the AC-D1 gate.

### Remaining (execution-time check, non-blocking)
- [ ] Confirm Paula's Choice product pages actually clear the AC-D1 ≥60% formulation/texture-token gate at ingestion; if under, hand-curate the shortfall (fallback already in plan Step 2).

### Deliberately out of scope for v1 (not open — recorded so they aren't re-raised)
- Reconciliation with `db/schema.sql` — intentionally dismissed (pure fresh start).
- Second traversal engine / materialized relational-adjacency — benchmark-only (R2); build only if AGE p95 breaches budget.
- `graph_relation_proposals` hybrid-expansion approval flow — deferred (no AC references it).
