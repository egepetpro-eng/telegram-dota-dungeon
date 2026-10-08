# Telegram Service and Server Deployment Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development and test-driven-development. Execute service tasks in dependency order; transport/views may run alongside storage after shared service interfaces are committed. Server inspection is already authorized; launch only verified behavior and report any remaining release gates honestly.

**Goal:** Connect the approved Dota card game to Telegram group/private controls, persist and recover matches, and deploy the bot as a Linux service on the user's server.

**Architecture:** Python service wraps `decide` in a per-game database transaction. Opaque callback tokens carry server-stored intentions; Telegram identities and chat context authorize actions. Persist state, RNG state, callbacks, timers and an outbox together. Long polling supplies incoming updates; workers process timers and outbox. Restart preserves offset and all deadlines.

**Tech Stack:** Python 3.12; PostgreSQL with psycopg 3; standard-library HTTPS Bot API client; systemd on Ubuntu 24.04. No incoming public HTTP listener is required for long polling.

**Spec:** `docs/superpowers/specs/2026-09-24-dota-munchkin-telegram-design.md`; consumes `core-engine.md`, `card-catalog-contract.md` and the accepted full catalog. Initial tests use small synthetic fixtures; public game startup validates the installed production release and media metadata.

## Global Constraints

- 2–6 players, one active match per group, simultaneous groups isolated; no hero selection.
- Private `/start` required before readiness. User may select among their active matches in private chat.
- Hidden hand appears only to its owner. Public profiles show level, equipment, carried items and visible identities/effects.
- Group: lobby, door, combat, help/interference, escape, rewards, win. Private: character, hand, equipment, prices, profiles, play and trade selectors.
- Reaction configured before start as 15/30/60 seconds (default 30). Help 60 seconds; trade 120 seconds; required-action idle warning/pause after 300 seconds. Pause preserves remaining timer durations.
- Server time and RNG are trusted service data. Every game pins its catalog version/digest. Repeated Telegram update/callback never replays a move or reward.
- Token/database credentials are environment configuration, never repository files or log output. Secrets supplied by user remain only in the coordinator's protected local store and remote environment file.
- Use provided server for deployment. Dedicated application user and directory `/opt/telegram-dota-dungeon`; service `telegram-dota-dungeon`; configuration `/etc/telegram-dota-dungeon.env` restricted to root. No modification of unrelated services.

## Review Focus

1. Forged/copied button for a different player/group/game: reject before `decide`, with no hidden-data disclosure. Task S2.
2. Process crashes between game commit and Telegram sending: recover game/outbox, never reapply the move. Bot API has no general send-message idempotency key; uncertain delivery may duplicate a notification, never game items/rewards. Task S1/S4.
3. A blocked private chat: retain player state, reject readiness/delivery-dependent setup and show the group a neutral reconnect instruction without revealing the hand. Tasks S3/S4.
4. Restart or pause during fight/trade/help: persisted deadlines execute once using version checks and trusted actor; stale timeout cannot affect a newer combat. Task S4.
5. A player active in two groups: every private selector retains game ID; switching context never retargets an old button. Task S2/S3.

## Files and Ownership

| Files | Responsibility |
| --- | --- |
| `src/dota_dungeon/service/codec.py`, `store.py`, `schema.sql` | Explicit JSON codec and PostgreSQL transactions, per-game locking, outbox/update uniqueness |
| `src/dota_dungeon/telegram/client.py`, `callbacks.py`, `views.py`, `router.py` | HTTP Bot API, server-backed callback intentions, Russian menus, routing/authorization |
| `src/dota_dungeon/service/timers.py`, `application.py`, `__main__.py` | Runtime composition, durable polling offset/timers/outbox and graceful shutdown |
| `deploy/telegram-dota-dungeon.service`, `deploy/env.example`, `docs/operations.md` | Linux service, configuration template without secrets, deployment/recovery instructions |
| `tests/test_service_{codec,store,callbacks,views,timers,recovery}.py` | Privacy, concurrent updates, persisted state and crash recovery |

Core changes for missing `leave_lobby`, `decline_help`, `cancel_trade` must go through the current C owner, source/spec-based tests and acceptance. Service does not mutate card zones behind `decide`. Pause/resume stores service status plus remaining deadlines; no game actions execute while paused. Core identity/card capability selectors expose only currently legal commands.

## S1 — Durable State and Transaction Boundary

**Interfaces:** `encode_state(state: GameState) -> dict`, `decode_state(raw: dict) -> GameState`; `GameRepository.apply(game_id: str, expected_version: int, update_id: str, transition: Callable) -> TransactionResult`. Transition returns next state/RNG/events/timers; transaction stores all and increments version, uniqueness of update ID prevents repeats. Reads scoped by game/group/user. Explicit schema versions support migrations; datetimes UTC ISO strings, sets/tuples tagged and type validated; never deserialize pickle.

- [ ] Test codec round trip on state with identity/equipment, active combat/help, trade, death zones, datetime, sets and request IDs; malformed schema/type rejects. Observe failures, implement codec, run tests.
- [ ] Add real PostgreSQL integration tests: two simultaneous actions with same expected version yield one success and one stale result; replay update yields no second event; failure rolls back state+outbox; different games remain independent. Use dedicated temporary test database configured by `TEST_DATABASE_URL`, never production data.
- [ ] Implement schema with games, private-chat links, callback intentions, incoming-update receipts, outbox and timers; unique active-group constraint; per-game row locking. Persist RNG `Random.getstate()` as validated JSON alongside state.
- [ ] Run codec/store tests against PostgreSQL and whole pytest; commit accepted S1.

## S2 — Safe Telegram Transport and Callbacks

**Interfaces:** `BotClient.call(method: str, payload: dict) -> dict`; `CallbackIntent(token: str, game_id: str, expected_version: int, actor_id: int | None, chat_id: int, action: str, args: dict, expires_at: datetime)`; `resolve_callback(token: str, telegram_user_id: int, chat_id: int, now: datetime) -> CallbackIntent`. Token contains 128+ random bits and stays below callback-data size limit; no raw hand IDs or commands in public callback text. Actor-null intentions are only lobby/public navigation actions, never private state edits.

- [ ] Test foreign player/group, expired/missing token, stale version, nonmember and command addressed to another bot. Verify every case rejects without transition or revealing secrets.
- [ ] Implement JSON POST client with timeouts, bounded retries/backoff for transport and 429, callback acknowledgements, safe HTML escaping and redacted errors. No token/HTTP URL in exception logs. Test injected HTTP transport with real response parsing, not assertions on mocked call counts.
- [ ] Persist callback intentions, read Telegram `from.id`/actual message chat, and enforce authorization before engine. `/start` deep link accepts an opaque lobby token; linking private chat never grants another user's identity.
- [ ] Run callback/client tests and full suite; commit S2.

## S3 — Group Lobby and Private Game Controls

**Interfaces:** `render_view(state: GameState, viewer_id: int, screen: str, release: CatalogRelease) -> View`; `route_update(update: dict, repository: GameRepository, bot: BotClient, now: datetime) -> None`. `View` contains destination, safe text/photo and server-side button intentions, never directly constructed callback payload commands.

- [ ] Write synthetic update scenarios: `/newgame`, two private `/start`, join/ready/start, six-player cap, leave before start; unauthorized host-start rejected; second active game in group rejected. Observe failing scenarios, implement flows.
- [ ] Implement Russian private screens: active match list, character/abilities, hand/card details, equipment/carried items, prices/sale selection, other public profiles, card play targets, help and trade composition/acceptance. Menus expose legal actions and allow selection cancellation without committing a move.
- [ ] Implement group turn/combat panels and event rendering; appropriate images use verified per-definition media binding via `sendPhoto`, retaining text-only delivery if a remote image is temporarily unavailable. Image errors never reveal another player's hand or prevent state recovery.
- [ ] Test multi-group navigation, public profile privacy, forged choices, actual card/equipment/trade transitions and readiness with unavailable private chat. Run full suite; commit S3.

## S4 — Timers, Recovery and Bot Runtime

**Interfaces:** `run_service(config: Config) -> None`; `tick_timers(now: datetime) -> int`; `deliver_outbox(now: datetime) -> int`. Configuration comes from env `BOT_TOKEN`, `DATABASE_URL`, `CATALOG_VERSION`, `LOG_LEVEL`; poller persists offset only after receiving update has been durably handled or safely recorded.

- [ ] Test restart of same saved database, expired help/trade/reaction, paused remaining durations, all-pass early close, stale timer for earlier combat, removal/readdition of bot and 300-second idle pause.
- [ ] Implement periodic persisted jobs with unique IDs/expected versions; use trusted active player for core close_reaction. Integrate decline/cancel core commands instead of mutating combat/trade data in adapters. Poll only relevant update types; keep privacy mode enabled.
- [ ] Persist outbox success/failure and retry times; forbidden-private delivery pauses readiness-dependent activity and offers reconnection. Do not put hidden card details into logs. Preserve uncertain-send behavior honestly; no claim of impossible exactly-once Telegram delivery.
- [ ] Implement graceful SIGTERM, service singleton polling lock, startup installed-catalog/media verification, health status and command registration. Run full recovery suites; commit S4.

## S5 — Install and Verify on Server

- [ ] Build wheel from reviewed branch; validate installed catalog and run full tests plus PostgreSQL recovery checks. Read server disk/OS/service state before installation; archive hash and commit identify deployed code.
- [ ] Install PostgreSQL if absent, create restricted app role/database and dedicated Linux application user, upload wheel/service/docs, create venv and environment file with supplied token plus generated DB credentials. Transfer secrets only through authenticated SSH/SFTP; exclude them from reports/history/Git.
- [ ] Configure systemd `User`, `WorkingDirectory`, `EnvironmentFile`, `ExecStart`, `Restart=on-failure`, `NoNewPrivileges=true`, explicit writable application state/cache paths. Set bot commands and use long polling without clearing pending updates.
- [ ] Start service; verify active status, process user, version/digest, DB connectivity, `getMe`, polling and clean redacted logs. Restart service and confirm persisted state/offset/timers. Save deployment SHA and operations instructions.
- [ ] Run a real two-player acceptance party when users open bot/add it to their group. If those human interactions are unavailable, report service verification separately from actual Telegram gameplay; never invent a played match. No DM to unrelated users or groups.

## Handoff

Finish with deployed commit/version, bot link, startup command for the group, verified checks and any factual catalog/gameplay gates still open. A running service is not proof that all original card exceptions are implemented.

Technical references checked 2026-10-08: [Telegram Bot API](https://core.telegram.org/bots/api), [deep linking](https://core.telegram.org/bots/features#deep-linking), [Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
