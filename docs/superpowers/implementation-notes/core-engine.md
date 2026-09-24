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

The engine has only a small test catalog. The 168-card mapping, Telegram transport, storage, timers, content rights and deployment remain separate work.

The catalog plan must extend command routing for card-specific cases not present in the small test catalog, especially `level_up`, noncombat `one_shot`, `special` cards and exceptions permitting multiple roles or races. Each new operation needs a failing rule test before being enabled.
