# Agent A — Catalog Brief

## Assignment

Implement Task 1, then the data portion of Task 7 from `docs/superpowers/plans/2026-10-08-dota-card-catalog.md`. Read that plan, its approved Spec, the core handoff and P0's `card-catalog-contract.md`. The coordinator supplies your worktree and accepted base SHA. Read only the context needed for this task; do not spawn agents.

## Owned Files

- `src/dota_dungeon/cards/data/classic-dota-v1/source-manifest.json`
- `src/dota_dungeon/cards/data/classic-dota-v1/catalog.json`
- `tests/test_card_manifest.py`
- `tests/fixtures/classic-checklist.json`
- `docs/superpowers/catalogs/classic-dota-v1-audit.md`

## Deliverables and Sequence

1. Capture the official checklist independently of production data and test physical totals 168, Doors 95, Treasures 73 and every printed copy count.
2. Verify original effects, costs, rewards and conditions. Record sources and corrections. Create stable rule keys and Dota mappings; keep repeated copies and classic item prices. No lobby hero selection, HP or mana.
3. Commit Task 1 and report the mapping so B can bind artwork and C can implement verified exceptions.
4. After the coordinator accepts the shared schema, write the full release, original Russian descriptions and a per-rule behavior coverage table. Work in parallel with C's engine tasks. An unimplemented rule stays an explicit gap until C supports it; do not weaken release validation to load it.
5. Run `python -m pytest tests/test_card_manifest.py -q`. Once C's accepted loader is available in your new task base, also run `python -m dota_dungeon.cards validate` and resolve factual/data failures within your ownership.

Do not edit core modules, media manifests, shared fixtures, CLI or packaging. Missing evidence is reported with the specific source fact needed; do not guess prices or change mappings to fit artwork. The coordinator integrates commits.

## Return Report

Return task ID, base/commit SHAs, changed files, tests and results, verified definition/instance counts, source gaps, mapping changes and any requested contract changes. Do not mark the full release complete merely because totals match.
