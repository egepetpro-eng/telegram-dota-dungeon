# Agent C — Loader and Engine Brief

## Assignment

Implement Task 2, then Tasks 3 → 4 → 5 → 6 from `docs/superpowers/plans/2026-10-08-dota-card-catalog.md`. Each task receives its own fresh implementer and accepted starting SHA. Read the relevant task, Global Constraints, approved Spec, `core-engine.md` and P0's frozen contract. Do not spawn agents.

## Owned Files

- `src/dota_dungeon/core/*.py`
- `src/dota_dungeon/cards/{__init__,release,schema,validation}.py`
- `tests/test_catalog_release.py`, `tests/test_card_{play,effects,draw,character,equipment,combat,bad_stuff}.py`
- Existing core tests and `tests/fixtures.py`, only when necessary to exercise a changed contract

## Deliverables and Sequence

1. Task 2 can run alongside source research using P0's clearly synthetic fixture/manifest. Build the closed schema, canonical digest, instance expansion and fact cross-checks. Prepare the special-rule registry and combat-card zone described in Task 2. Declaring a handler in a contract does not mean it is implemented.
2. Return Task 2 for review and integration. Start Task 3 only from the coordinator's accepted base containing Task 1/2; use verified evidence for original card exceptions.
3. Execute card play/effect selectors, draw pipeline, character/equipment exceptions and special combat in plan order. These tasks share models and command routing, so only one C task runs at a time.
4. For every feature: write the rule test, observe its failure, implement, run relevant tests and commit. Preserve `decide(state, command, catalog, rng)`, request idempotency, one physical zone per card, private-hand visibility and explicit winning-level exceptions.
5. Run `python -m pytest -q` after accepted engine stages. Return unsupported manifest rule keys as specific gaps; do not discard unknown effects or compare mechanics using display names.

Do not edit A's source/release JSON, B's media files, coordinator's acceptance/media tests, CLI or packaging. Suggest data/contract fixes with evidence; the owner makes them. Return a commit after each reviewed task, not one unreviewable change spanning all engine rules.

## Return Report

Return task ID, base/commit SHAs, changed files, red/green evidence, full test results, supported operations/handler keys, unresolved card cases and requested contract changes. The coordinator integrates commits and advances dependent tasks.
