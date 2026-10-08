# Core engine handoff

The approved plan is the design baseline. These interface details were settled during implementation and must be used by the card catalog and Telegram adapter.

- `decide(state, command, catalog, rng)` is the only public command boundary. A persistence transaction must load one game's state, call `decide`, save the returned state and events together, and only then deliver events. `request_id` is unique within that game.
- `new_lobby` puts every physical card ID in exactly one unshuffled deck. `start` shuffles them and deals four Door and four Treasure cards to each player. `GameState.card_decks` records each card's source deck so charity and death can discard correctly.
- `open_door`, `loot_room` and `end_turn` accept an optional RNG. The adapter should pass its game RNG so recycling and rebirth are reproducible.
- `ask_help` requires `catalog` after `item_ids`; `play_combat_card` requires trusted `now` after `catalog`; `offer_trade` requires `catalog` and trusted `now` after `expires_at`. The adapter must derive `now` server-side, never from callback payload text.
- Additional commands are `play_identity`, `declare_win`, `pass_reaction`, `begin_escape`, `expire_trade` and `loot_corpse`. `close_reaction` is active-player-only through `decide`; a timer may submit it under the active player's ID.
- `CardDef` adds `treasures`, `levels` and `bad_stuff` to the originally planned fields. A monster's `bonus` is its combat level. The full catalog must validate each of these declarations.
- `Event.audience` is `group`, `actor` or `user:<id>`. Solo treasure draws use explicit `user:<fighter id>`; group events must never include hidden card IDs.
- Starting a fighter's combat cancels their pending trades. `offer_trade` permits expiry at most two minutes after trusted `now`; `expire_trade` changes an elapsed offer to expired. The adapter schedules that command.

The shipped factual mapping contains 168 physical cards. Character and equipment
exceptions have passed task review; remaining card-specific effects and final
installed-release acceptance are tracked in the catalog plan. Telegram storage,
transport and timers are implemented separately; production deployment follows
the complete release gate.

The catalog plan must extend command routing for card-specific cases not present in the small test catalog, especially `level_up`, noncombat `one_shot`, `special` cards and exceptions permitting multiple roles or races. Each new operation needs a failing rule test before being enabled.

## Accepted character and equipment interface

- Source underscore ability keys are canonical; planned dotted aliases remain
  compatible. `use_ability` takes `ability_key`, `target`, `cost_ids`, trusted
  `now`. Sources, costs, counters and timing are validated in core.
- Share `is_item_card`, `effective_hand_limit` and `combat_totals` with the UI.
  Printed No Value one-shots are Items; carried unused Items give no permanent
  equipment bonus. There is no gold wallet.
- `carry_item(card_id)`, `assign_hireling(hireling_id,card_id)` and
  `discard_identity(card_id)` preserve the original physical cards. Hireling
  reassignment leaves its former Item carried and unequipped. Attachment and
  identity lists index cards in `in_play`; they are not additional card zones.
- Pending excess is resolved through `resolve_identity_excess(card_ids)` or
  `resolve_big_items(card_ids,recipient_id?)`; ordinary actions wait for these
  choices. A narrowly legal own-turn Big Item sale may also resolve the excess.
- `set_character_sex(character_sex)` accepts male/female/null in the lobby.
  An unset value is assigned by the injected game RNG at start. Artwork and
  Telegram profiles do not determine this trait.
- A production `run_away(monster_id)` stores one die independently of all hidden
  hands. `resolve_escape(monster_id)` settles it before another attempt or
  unrelated action. Only explicitly allowed after-roll abilities/cards may
  change that unresolved result. Service continuation deadlines must preserve
  this opportunity after restart.
- `CombatState.charmed_monster_ids` is a physical reservation zone, alongside
  `monster_ids` and `played_card_ids`. Count it once in conservation checks.
- JSON persistence preserves all character counters, ownership references,
  pending excess and unresolved escape dice. Actual restored command execution
  is tested in `tests/test_service_codec.py`.
