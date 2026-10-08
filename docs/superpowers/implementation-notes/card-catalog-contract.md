# Card catalog contract v1

This document freezes P0 interfaces for the parallel plan `2026-10-08-dota-card-catalog.md`. The approved design and original verified card rules remain the authority. Coordinator owns changes to this contract. No production release may invent missing source facts or treat a named handler as implemented.

## Catalog data

- Source manifest: `{version: str, cards: list[SourceRecord]}`. Source records are keyed by unique `rule_key`, use positive integer `copies` and contain `source_name`, `deck`, `kind`, all mechanics fields below, `source_refs: list[str]`, `verified_on: YYYY-MM-DD`, `dota_entity_id: str`, `display_name_ru: str`. Additional `evidence_status: verified | unresolved` and `evidence_notes: str` record incomplete facts. Unresolved records cannot validate for production. A factual source may be a publisher-authored card or correction; a link alone is not proof of its numeric contents.
- Release JSON: `{version: str, definitions: dict[str, Definition], instances: dict[str, str], digest?: str}`.
- `Definition = {presentation: {display_name_ru, description_ru, dota_entity_id, source_refs}, mechanics: Mechanics}`. Presentation strings must be nonempty; source_refs is a nonempty list of nonempty strings.
- Every definition key equals one manifest rule_key. Physical instance IDs are `<rule_key>:<copy_number>` with numbering from 1. Instances map ID to definition key. Counts must equal each manifest `copies`; no missing or extra definitions. Full release additionally requires 168 instances, 95 Doors and 73 Treasures. Synthetic fixtures may be smaller.
- Digest: SHA-256 of UTF-8 JSON excluding top-level `digest`, using `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`. Declared digest must equal computed digest. Source fact comparison includes all mechanics, excluding copies/evidence/display metadata; no display-name comparison controls game rules.

## Mechanics fields and validation

Required: `deck: door | treasure`, `kind: monster | curse | role | race | modifier | item | one_shot | level_up | special`. Defaults: `value=0`, `bonus=0`, `slots=null`, `size=small`, `effects=[]`, `tags=[]`, `treasures=0`, `levels=1`, `bad_stuff=[]`, `play_phases=[]`, `target_rule=none`, `restrictions={}`, `conditions=[]`, `abilities=[]`, `trigger=null`.

- Numeric fields use exact Python int, excluding bool. `value`, `treasures` are nonnegative; `levels` is positive; `bonus` may be negative. Physical counts are positive.
- `slots`: null, `head`, `armor`, `feet`, `one_hand`, `two_hands`. These are data values; the loader adapts to current engine slot conventions as necessary, without changing their meaning.
- `size`: `small | big`; `tags`: unique strings. Roles/races/conditions use stable source keys (e.g. `warrior`, `elf`), never Dota display strings.
- `play_phases`: unique values from `turn.prepare`, `turn.after_door`, `turn.charity`, `combat.active`, `combat.run_away`. Empty means no player-initiated play. Neither lobby nor finished state permits normal play.
- `target_rule`: `none | self | player | monster | open_item | identity | discard | combat`. Commands use `target` dictionaries with the appropriate `player_id`, `monster_id` or `card_id`; an explicit selector validates the owner's eligible cards. No client-supplied target grants permission to another hidden hand.
- `restrictions`: closed keys `role_any`, `race_any`, `cannot_use_roles`, `cannot_use_races` (unique lists of stable keys), `sex` (`male | female`), `requires_rule` (stable key). Item permissions changing slot or carrying capacity are explicit source-backed handlers, not arbitrary integer flags supplied by clients.
- `conditions`: list of `{rule_key: str, args: dict}`. `trigger`: null or `{rule_key: str, timing: acquired | initial_deal, visibility: inherit | group, args: dict}`. Ability descriptors: `{key: str, cost: {zone: hand | in_play | either, count: nonnegative int}, limit: {scope: combat | escape_attempt | turn | unlimited, max_uses: positive int | null}, phases: list[phase]}`. Handlers validate their own closed argument schemas. Unknown conditions/triggers/abilities or unknown handler args reject a runnable release.
- Generic effects retain existing op names: `gain_level`, `lose_level`, `add_strength`, `remove_item`, `persistent`, `draw`, `monster_modifier`, `escape_modifier`, `prevent_bad_stuff`, `kill_monster`, `remove_monster`. Gain/lose/draw `amount` is positive (default 1); strength/modifiers use signed integer amount. Draw `deck` is door/treasure (default treasure). Exact ID operands are supported for compatibility; production selectors resolve them server-side. `gain_level.can_win` is boolean (default false) and is only allowed for a verified winning exception.
- New special-effect descriptor: `{op: special, rule_key: str, args: dict}`. A release containing it may load only when that key's real handler is registered and its arguments validate. Source research may propose keys before implementation; that does not enable loading. Existing test catalogs retain `load_catalog` behavior and defaults.
- Reject unknown keys, wrong operand types and nested unknown operations. Every newly needed opcode/selector requires a contract amendment plus schema and behavior tests, with evidence from the source manifest.

## Python and command boundaries

`Catalog = dict[str, CardDef]` stays keyed by physical ID. Frozen `CardPresentation(display_name_ru: str, description_ru: str, dota_entity_id: str, source_refs: tuple[str, ...])` and `CatalogRelease(version: str, digest: str, catalog: Catalog, presentations: dict[str, CardPresentation])`; presentations are keyed by physical ID as well. Loader reads `source-manifest.json` next to the release path; `validate_release(raw: dict, manifest: dict) -> None` performs both shape and factual checks. Public release loading rejects incomplete evidence and unimplemented handlers.

CardDef gains defaulted `rule_key`, `play_phases`, `target_rule`, `restrictions`, `trigger`, `conditions`, `abilities` to represent all contract fields without discarding information. GameState gains optional catalog_version/catalog_digest. CombatState gains `played_card_ids`, a physical zone; modifier_ids remain references for cards stored there. Existing older modifier cards must be migrated into one physical combat zone during revised play. Task 3 owns regular combat cleanup; Task 6 owns new exceptional completion paths.

`decide(state, command, catalog, rng)` is unchanged. New commands `play_card`, `use_ability`, `set_character_sex` route through it. `now` is trusted service time, not a user-controlled Telegram callback. Repeated request IDs are no-ops. Failed transitions preserve input state and card zones. Numeric costs come from verified records; a caller may select cards but cannot change the price or effect strength.

## Media v1

Candidates: `{schema_version: 1, assets: dict[str, Asset]}`. Asset fields: `dota_entity_id`, `image_url`, `original_publication_url`, `credit`, `asset_kind`, `verified_on`, `status`, `notes`, all strings. `asset_kind`: `portrait | icon | official_art | loading_screen | wallpaper | promo`; status: `candidate | verified | rejected`. HTTPS source URLs required. Verification means inspected image and attributable primary publication, not just a working URL or a fan-art search result.

Selected manifest: `{media_version: str, catalog_version: str, catalog_digest: str, assets: dict[str, Asset], bindings: dict[str, str]}`. Bindings map every definition rule_key to a selected verified asset_id depicting the mapped entity. Repeated physical copies share their definition binding. Original portraits/icons are acceptable fallbacks for the same entity. Catalog changes invalidate old version/digest pins. Selected assets require primary provenance and credit. The coordinator's `validate_media_manifest(raw: dict, release: CatalogRelease) -> None` rejects mismatch with actionable ValueError messages. Runtime renderer/local image preparation is a later Telegram task; this stage supplies source metadata.

## Ownership and integration

A writes factual/release data and rule audit. B writes media data and media audit. C writes loader/core code and its tests. Coordinator writes this contract, CLI, packaging, acceptance/media tests and integration records. Each task has a fresh implementer; shared code tasks run sequentially. Findings are returned to the owner; workers never merge/push or edit another worktree. Reports include source evidence, changed files, base/commit SHAs, red/green/full-suite results and unresolved gaps.
