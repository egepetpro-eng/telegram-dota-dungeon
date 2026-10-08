# Agent B — Official Artwork Brief

## Assignment

Implement M1 and then M2 from `docs/superpowers/plans/2026-10-08-dota-card-catalog.md`. Read its Spec's artwork requirements and P0's media contract. The coordinator supplies your worktree/base SHA and accepted mapping when available. Do not spawn agents.

## Owned Files

- `src/dota_dungeon/cards/data/classic-dota-v1/media-candidates.json`
- `src/dota_dungeon/cards/data/classic-dota-v1/media.json`
- `docs/superpowers/catalogs/classic-dota-v1-media-audit.md`

## Deliverables and Sequence

1. Search beyond dota2.com: original game portraits/icons, official artwork, loading screens, wallpapers and promotional illustrations, including Steam, official channels and artists' portfolios.
2. Index candidates by stable Dota entity ID. Record image and primary-publication URLs, author/publisher, kind, date, status and inspection notes. A repost is acceptable as a file host when original authorship is verified.
3. Commit M1 and report available entities plus specific gaps. M1 can run before A finishes card mappings.
4. After A's accepted mapping, select a recognisable verified image for every unique rule key, preserving entity identity. Use the same image for repeated copies; if no suitable art is found, use that entity's verified original portrait/icon. Report unresolved gaps rather than assigning unrelated imagery.
5. After the final playable catalog is available, pin bindings to its exact version/digest. Inspect selected imagery for readability at small card size and complete the media audit. Return M2 for metadata tests and coordinator review.

Do not change mechanics, Dota mappings, card descriptions, core code or A's audit. Media research does not require artificial tests against changing websites. The coordinator owns `tests/test_card_media.py` and integrates your commits. This task delivers verified source metadata and selections; renderer, local asset preparation and Telegram image delivery belong to the Telegram/media implementation stage.

## Return Report

Return task ID, base/commit SHAs, changed files, candidate/verified counts, bound-definition count, primary sources, inspection results and missing entities/sources. Distinguish candidates from verified selected images.
