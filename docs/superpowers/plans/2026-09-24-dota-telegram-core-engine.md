# Dota Telegram Game Core Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать проверяемый движок партии на 2–6 игроков с базовыми правилами классического «Манчкина», независимый от Telegram и оформления карт Dota 2.

**Architecture:** Чистая функция `decide` принимает состояние партии, команду игрока, каталог и источник случайности, затем возвращает новое состояние и события с пометкой видимости. Движок не вызывает Telegram API и не хранит данные сам. Следующие отдельные планы подключат полный каталог из 168 тематических карт и Telegram-адаптер с постоянным хранилищем.

**Tech Stack:** Python 3.12, стандартная библиотека, pytest 8. Для Telegram-адаптера следующего плана выбран aiogram 3; для постоянного хранения — PostgreSQL. [Документация aiogram](https://docs.aiogram.dev/en/latest/), [Telegram Bot API](https://core.telegram.org/bots/api).

**Spec:** `docs/superpowers/specs/2026-09-24-dota-munchkin-telegram-design.md`

## Global Constraints

- Партия: **2–6 игроков**, один активный матч в группе; состояния разных групп изолированы.
- Каждый начинает с уровня 1 без класса и расы и получает **4 карты дверей и 4 карты сокровищ**.
- Полный каталог продукта: **168 карт: 95 дверей и 73 сокровища**. В этом плане движок работает с небольшой тестовой колодой; отдельный план наполнит каталог целиком.
- Победа: **10-й уровень после убийства монстра**, кроме прямого исключения на карте.
- «Золото» в классическом режиме означает **стоимость вещей**, а не счёт монет; каждые полные 1000 золотых стоимости дают уровень при продаже на своём ходу, без достижения уровня 10.
- Рука игрока скрыта; карты в игре открыты. После хода в руке не более пяти карт.
- Обмен допускает только выложенные вещи и запрещён, если хотя бы одна сторона в бою.
- Все игровые действия имеют идентификатор запроса. Повтор одного запроса не меняет состояние второй раз.
- Правила разрешения фаз и карт сверяются с [официальными правилами классического издания](https://munchkin.game/site-munchkin/assets/files/1138/munchkin_rules-1.pdf) и [FAQ](https://munchkin.game/gameplay/faq/).

## Review Focus

1. **Два игрока с одинаковым минимальным уровнем:** лишние карты активного игрока сбрасываются, а не передаются оппоненту; проверить в Task 3.
2. **Повтор callback с тем же request ID:** вторая обработка не тянет карту и не передаёт вещь; проверить в Tasks 2 и 4.
3. **Изменение силы во время окна боя:** прежнее решение о победе отменяется, итог пересчитывается после нового эффекта; проверить в Task 5.
4. **Продажа вещей на уровне 9:** операция не создаёт победный уровень и не уничтожает выбранные вещи; проверить в Task 4.
5. **Смерть помощника и несколько монстров:** броски побега и плохие исходы применяются отдельно; проверить в Task 5.

## File Map

| Файл | Ответственность |
| --- | --- |
| `telegram-dota-dungeon/pyproject.toml` | Метаданные Python-пакета и тестовые зависимости. |
| `telegram-dota-dungeon/src/dota_dungeon/core/model.py` | Типы карт, игрока, боя, сделки и партии. |
| `telegram-dota-dungeon/src/dota_dungeon/core/catalog.py` | Загрузка и проверка определений карт. |
| `telegram-dota-dungeon/src/dota_dungeon/core/effects.py` | Применение описанных в каталоге эффектов карт. |
| `telegram-dota-dungeon/src/dota_dungeon/core/setup.py` | Лобби, готовность, стартовая раздача, порядок ходов. |
| `telegram-dota-dungeon/src/dota_dungeon/core/turn.py` | Открытие двери, обыск, вызов монстра, милостыня и передача хода. |
| `telegram-dota-dungeon/src/dota_dungeon/core/items.py` | Слоты, экипировка, стоимость и продажа вещей. |
| `telegram-dota-dungeon/src/dota_dungeon/core/trade.py` | Предложение и атомарное принятие обмена. |
| `telegram-dota-dungeon/src/dota_dungeon/core/combat.py` | Силы, помощь, помехи, награды, побег и смерть. |
| `telegram-dota-dungeon/src/dota_dungeon/core/engine.py` | Проверка команды, идемпотентность и маршрутизация в модуль правил. |
| `telegram-dota-dungeon/tests/fixtures.py` | Малые каталоги, фиксированные броски и фабрики тестовых партий. |
| `telegram-dota-dungeon/tests/test_*.py` | Тесты публичных сценариев движка. |

Рабочий код живёт в новом каталоге `telegram-dota-dungeon/`, отдельно от находящегося рядом репозитория `superpowers/`. При старте реализации инициализировать Git именно в `telegram-dota-dungeon/`; скопировать туда утверждённую спецификацию и этот план, чтобы они были версионированы вместе с кодом. Каждый Task заканчивается коммитом в этом репозитории.

---

### Task 1: Domain Contracts and Card Schema

**Files:**
- Create: `telegram-dota-dungeon/pyproject.toml`
- Create: `telegram-dota-dungeon/src/dota_dungeon/__init__.py`
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/model.py`
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/catalog.py`
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/effects.py`
- Test: `telegram-dota-dungeon/tests/test_catalog.py`
- Test: `telegram-dota-dungeon/tests/test_effects.py`

**Interfaces:**
- Consumes: Python 3.12.
- Produces: `CardDef`, `Player`, `Trade`, `CombatState`, `CombatDecision`, `GameState`, `Command`, `Event`, `RuleError`, `Catalog`, `load_catalog(raw: dict) -> Catalog`, and `apply_effects(state: GameState, target_id: int, effects: list[dict], catalog: Catalog) -> tuple[GameState, list[Event]]`. Later tasks import these names exactly.

- [ ] **Step 1: Create the package and write a failing catalog test.** `pyproject.toml` contains the following package configuration, and the test rejects duplicate physical card IDs and unknown deck names:

```toml
[build-system]
requires = ["setuptools>=75,<81"]
build-backend = "setuptools.build_meta"

[project]
name = "telegram-dota-dungeon"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=8,<9"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

```python
import pytest
from dota_dungeon.core.catalog import load_catalog

def test_catalog_rejects_duplicate_instance_ids():
    raw = {"cards": [
        {"id": "door-1", "deck": "door", "kind": "monster", "name": "Creep", "value": 0},
        {"id": "door-1", "deck": "door", "kind": "monster", "name": "Creep", "value": 0},
    ]}
    with pytest.raises(ValueError, match="duplicate card id"):
        load_catalog(raw)
```

- [ ] **Step 2: Run `python -m pytest tests/test_catalog.py -q` and confirm the import fails.**
- [ ] **Step 3: Define the domain types and loader.** `CardDef` has `id`, `deck`, `kind`, `name`, `value`, `bonus`, `slots`, `size`, `effects` and `tags`; for a monster `bonus` is its printed level. `Player` has `user_id`, `level`, `hand`, `in_play`, `equipped`, `ready`, `role_ids`, `race_ids`, `alive`; `Trade` has `id`, `sender_id`, `receiver_id`, `offered_ids`, `requested_ids`, `expires_at`, `status`; `GameState` has `game_id`, `group_id`, `host_id`, `phase`, `active_user_id`, `order`, `players`, both deck stacks and discards, optional `combat`, `trades`, and `processed_requests: set[str]`. `CombatState` stores fighter IDs, optional helper ID, monster IDs, modifier IDs, passes and `reaction_deadline`; `CombatDecision` stores `outcome: Literal["provisional_win", "must_run_away"]`. Define `Command(game_id, actor_id, request_id, name, args)` and `Event(audience, name, data)` as dataclasses. Audience is `group`, `actor` or `user:<Telegram ID>`. Set `Catalog = dict[str, CardDef]` and define `RuleError(ValueError)`. Validate unique IDs, decks (`door`, `treasure`), kinds (`monster`, `curse`, `role`, `race`, `modifier`, `item`, `one_shot`, `level_up`, `special`), and nonnegative value.

```python
def load_catalog(raw: dict) -> Catalog:
    cards: dict[str, CardDef] = {}
    for entry in raw["cards"]:
        if entry["id"] in cards:
            raise ValueError("duplicate card id")
        if entry["deck"] not in {"door", "treasure"}:
            raise ValueError("invalid deck")
        cards[entry["id"]] = CardDef.from_dict(entry)
    return cards
```

- [ ] **Step 4: Add tests for invalid deck, negative value, missing ID and valid duplicate names with distinct IDs.** Duplicate printed card names are allowed because physical copies have distinct IDs. In `effects.py`, dispatch explicit effect operations `gain_level`, `lose_level`, `add_strength`, `remove_item`, `persistent`, `draw`, `monster_modifier`, `escape_modifier`, `prevent_bad_stuff`, `kill_monster`, and `remove_monster`; reject an unknown operation while loading the catalog. Test `lose_level` at level 1, `gain_level` at level 9, and an unknown operation:

```python
def test_curse_never_reduces_below_level_one(level_one_game, catalog):
    state, _ = apply_effects(level_one_game, 101, [{"op": "lose_level", "amount": 2}], catalog)
    assert state.players[101].level == 1

def test_level_card_cannot_grant_winning_level(level_nine_game, catalog):
    with pytest.raises(RuleError, match="winning level"):
        apply_effects(level_nine_game, 101, [{"op": "gain_level", "amount": 1}], catalog)
```

Run `python -m pytest tests/test_catalog.py tests/test_effects.py -q`.
- [ ] **Step 5: Initialize Git inside `telegram-dota-dungeon/`, copy the approved spec and this plan into `docs/superpowers/`, then commit with `git commit -m "feat: define game domain and card schema"`.**

### Task 2: Lobby, Readiness, and Initial Deal

**Files:**
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/setup.py`
- Create: `telegram-dota-dungeon/tests/fixtures.py`
- Test: `telegram-dota-dungeon/tests/test_setup.py`

**Interfaces:**
- Consumes: `GameState`, `Player`, `Event`, `Catalog` from Task 1.
- Produces: `new_lobby(game_id: str, group_id: int, host_id: int, catalog: Catalog) -> GameState`; `join(state: GameState, user_id: int) -> tuple[GameState, list[Event]]`; `set_ready(state: GameState, user_id: int, ready: bool) -> tuple[GameState, list[Event]]`; `start(state: GameState, actor_id: int, catalog: Catalog, rng: random.Random) -> tuple[GameState, list[Event]]`. Illegal requests raise `RuleError`.

- [ ] **Step 1: Write tests for start with 1 player (rejected), with 2 and 6 ready players (accepted), and with 7 players (rejected).** Use a fixture catalog with at least 24 Door and 24 Treasure instances to cover six initial hands.

```python
def test_two_ready_players_can_start(lobby, rng):
    state, _ = join(lobby, 101)
    state, _ = join(state, 102)
    state, _ = set_ready(state, 101, True)
    state, _ = set_ready(state, 102, True)
    state, events = start(state, lobby.host_id, catalog, rng)
    assert state.phase == "turn.prepare"
    assert [len(state.players[u].hand) for u in (101, 102)] == [8, 8]
    assert all(state.players[u].level == 1 for u in (101, 102))
    assert all(event.audience != "group" for event in events if event.name == "hand.dealt")
```

- [ ] **Step 2: Run `python -m pytest tests/test_setup.py -q` and confirm failure.**
- [ ] **Step 3: Implement lobby validation and deterministic setup.** Shuffle Door and Treasure IDs separately using injected `random.Random`, deal four from each per player, set no class/race, select first player with the same RNG, and emit private `hand.dealt` events plus one public `game.started` event. Do not send messages from this module.

```python
if not 2 <= len(state.order) <= 6:
    raise RuleError("game requires 2 to 6 players")
if any(not state.players[user_id].ready for user_id in state.order):
    raise RuleError("all players must be ready")
doors = [card.id for card in catalog.values() if card.deck == "door"]
treasures = [card.id for card in catalog.values() if card.deck == "treasure"]
rng.shuffle(doors)
rng.shuffle(treasures)
for user_id in state.order:
    state.players[user_id].hand = [doors.pop() for _ in range(4)] + [treasures.pop() for _ in range(4)]
```
- [ ] **Step 4: Run setup tests; add a test ensuring the same seeded RNG reproduces deck order and that one card ID never belongs to two zones.**
- [ ] **Step 5: Commit with `git commit -m "feat: start two to six player games"`.**

### Task 3: Turn Phases and Charity

**Files:**
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/turn.py`
- Test: `telegram-dota-dungeon/tests/test_turn.py`

**Interfaces:**
- Consumes: `GameState`, `Catalog`, `Event`, `RuleError` from Tasks 1–2.
- Produces: `open_door(state: GameState, actor_id: int, catalog: Catalog) -> tuple[GameState, list[Event]]`; `seek_trouble(state: GameState, actor_id: int, card_id: str, catalog: Catalog) -> tuple[GameState, list[Event]]`; `loot_room(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]`; `give_charity(state: GameState, actor_id: int, assignments: dict[int, list[str]]) -> tuple[GameState, list[Event]]`; `end_turn(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]`.

- [ ] **Step 1: Write tests for a public monster door, immediately applied curse, private room loot, and no room loot after a door monster.**

```python
def test_loot_room_stays_private(after_nonmonster_door):
    state, events = loot_room(after_nonmonster_door, after_nonmonster_door.active_user_id)
    assert state.phase == "turn.charity"
    assert any(e.name == "card.drawn" and e.audience == "actor" for e in events)
    assert not any(e.name == "card.drawn" and e.audience == "group" for e in events)
```

- [ ] **Step 2: Run `python -m pytest tests/test_turn.py -q` and confirm failure.**
- [ ] **Step 3: Implement the phase transitions.** Opening a door pops exactly one Door card. A monster enters `combat.active`; a curse resolves immediately; other cards can enter the active player's hand after their public reveal. Without a door monster, only `seek_trouble` with a monster from the actor's hand or `loot_room` is legal. A successful or failed fight flows to `turn.charity`.

```python
card_id = state.door_deck.pop()
card = catalog[card_id]
events = [Event("group", "door.revealed", {"card_id": card_id})]
if card.kind == "monster":
    state.phase = "combat.active"
    state.combat = CombatState(monster_ids=[card_id], fighter_ids=[actor_id])
elif card.kind == "curse":
    state.phase = "turn.after_door"
    state.door_discard.append(card_id)
    state, effect_events = apply_effects(state, actor_id, card.effects, catalog)
    events.extend(effect_events)
    events.append(Event("group", "curse.applied", {"card_id": card_id, "target_id": actor_id}))
else:
    state.phase = "turn.after_door"
    state.players[actor_id].hand.append(card_id)
return state, events
```
- [ ] **Step 4: Add charity tests.** With six cards, the active lowest-level player discards one. With a unique lower-level opponent, the actor assigns one to that opponent. With tied lowest opponents, assignments differ by at most one. `end_turn` refuses while the actor has more than five cards.

```python
def test_two_player_tied_lowest_discards_extra(two_player_charity):
    state, events = give_charity(two_player_charity, 101, {})
    assert len(state.players[101].hand) == 5
    assert len(state.players[102].hand) == 5
    assert any(event.name == "charity.discarded" for event in events)
```
- [ ] **Step 5: Run `python -m pytest tests/test_turn.py -q`; commit with `git commit -m "feat: implement turn phases and charity"`.**

### Task 4: Items, Gold Value, and Atomic Trades

**Files:**
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/items.py`
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/trade.py`
- Test: `telegram-dota-dungeon/tests/test_items.py`
- Test: `telegram-dota-dungeon/tests/test_trade.py`

**Interfaces:**
- Consumes: `GameState`, `CardDef`, `Catalog`, `Event`, `RuleError`.
- Produces: `equip(state: GameState, actor_id: int, card_id: str, catalog: Catalog) -> tuple[GameState, list[Event]]`; `unequip(state: GameState, actor_id: int, card_id: str) -> tuple[GameState, list[Event]]`; `sell(state: GameState, actor_id: int, card_ids: list[str], catalog: Catalog) -> tuple[GameState, list[Event]]`; `remove_owned_card(player: Player, card_id: str) -> None`; `offer_trade(state: GameState, actor_id: int, partner_id: int, offered_ids: list[str], requested_ids: list[str], expires_at: datetime) -> tuple[GameState, list[Event]]`; `accept_trade(state: GameState, actor_id: int, trade_id: str, catalog: Catalog, now: datetime) -> tuple[GameState, list[Event]]`; `transfer_items(sender: Player, receiver: Player, card_ids: list[str]) -> None`.
- Also produces: `validate_trade_transfer(seller: Player, buyer: Player, trade: Trade, catalog: Catalog) -> None`; this checks both sets of card IDs and resulting Big-item limits before any transfer.

- [ ] **Step 1: Write tests for one head slot, one armor slot, one footwear slot, two one-hand items or one two-hand item, and a carried item that grants no bonus.**

```python
def test_cannot_equip_two_head_items(game_with_two_helmets, catalog):
    state, _ = equip(game_with_two_helmets, 101, "helmet-a", catalog)
    with pytest.raises(RuleError, match="head slot"):
        equip(state, 101, "helmet-b", catalog)
```

- [ ] **Step 2: Run item tests and confirm failure.** Implement slot checks and the `carried` versus `equipped` distinction; do not permit normal re-equipping in combat.

```python
if state.phase == "combat.active":
    raise RuleError("cannot change equipment in combat")
occupied = [catalog[item_id].slots for item_id in player.equipped]
if card.slots == "head" and "head" in occupied:
    raise RuleError("head slot is occupied")
if card.slots == "two_hands" and any(slot in {"one_hand", "two_hands"} for slot in occupied):
    raise RuleError("hand slots are occupied")
```
- [ ] **Step 3: Write sale tests for value 900 (rejected), 1100 (one level, no change), 2000 (two levels), sale outside own turn (rejected), and level 9 to 10 (rejected with cards retained).** Implement sale as one validated transition: compute available gains and cap before removing any card.

```python
total = sum(catalog[card_id].value for card_id in card_ids)
gained = total // 1000
if gained < 1 or player.level + gained >= 10:
    raise RuleError("sale cannot grant the winning level")
if actor_id != state.active_user_id or state.phase in {"combat.active", "combat.run_away"}:
    raise RuleError("sale is allowed only on your turn outside combat")
for card_id in card_ids:
    remove_owned_card(player, card_id)
    state.treasure_discard.append(card_id)
player.level += gained
```
- [ ] **Step 4: Write trade tests for hand card rejection, an active combat rejection, offer expiry, changed card ownership, and double accept.** Implement `accept_trade` by checking all conditions against current state before moving any card; mark the offer `accepted` in the returned state. An offer reserves its card IDs so two pending offers cannot promise the same item.

```python
if trade.status != "pending" or now >= trade.expires_at:
    raise RuleError("trade is no longer available")
if trade.offered_ids != list(dict.fromkeys(trade.offered_ids)):
    raise RuleError("duplicate offered item")
if not all(card_id in seller.in_play for card_id in trade.offered_ids):
    raise RuleError("offered item changed owner")
if not all(card_id in buyer.in_play for card_id in trade.requested_ids):
    raise RuleError("requested item changed owner")
if state.combat is not None and (seller.user_id in state.combat.fighter_ids or buyer.user_id in state.combat.fighter_ids):
    raise RuleError("cannot trade during combat")
validate_trade_transfer(seller, buyer, trade, catalog)
transfer_items(seller, buyer, trade.offered_ids)
transfer_items(buyer, seller, trade.requested_ids)
trade.status = "accepted"
```
- [ ] **Step 5: Run `python -m pytest tests/test_items.py tests/test_trade.py -q`; commit with `git commit -m "feat: manage equipment gold value and trades"`.**

### Task 5: Combat, Help, Rewards, Escape, and Death

**Files:**
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/combat.py`
- Test: `telegram-dota-dungeon/tests/test_combat.py`

**Interfaces:**
- Consumes: `GameState`, `CardDef`, `Catalog`, `Event`, `RuleError`, injected `random.Random`.
- Produces: `combat_strength(state: GameState, user_id: int, catalog: Catalog) -> int`; `ask_help(state: GameState, actor_id: int, helper_id: int, treasure_count: int, item_ids: list[str]) -> tuple[GameState, list[Event]]`; `accept_help(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]`; `play_combat_card(state: GameState, actor_id: int, card_id: str, target_id: str, catalog: Catalog) -> tuple[GameState, list[Event]]`; `declare_result(state: GameState, actor_id: int, catalog: Catalog) -> CombatDecision`; `close_reaction(state: GameState, catalog: Catalog, now: datetime) -> tuple[GameState, list[Event]]`; `run_away(state: GameState, actor_id: int, monster_id: str, rng: random.Random, catalog: Catalog) -> tuple[GameState, list[Event]]`; `escape_modifier(state: GameState, actor_id: int, monster_id: str, catalog: Catalog) -> int`; `apply_bad_stuff(state: GameState, actor_id: int, monster_id: str, catalog: Catalog) -> tuple[GameState, list[Event]]`; `resolve_rewards(state: GameState, catalog: Catalog) -> tuple[GameState, list[Event]]`.
- `ask_help` also accepts `item_ids: list[str]` as its fifth argument for a promised open item; validate that each ID belongs to the active fighter before publishing the offer.

- [ ] **Step 1: Write strength tests for strict greater-than victory, monster winning a tie, equipment/role bonuses, one helper, and multiple monsters added to the same fight.**

```python
def test_monster_wins_equal_strength(equal_strength_combat, catalog):
    result = declare_result(equal_strength_combat, 101, catalog)
    assert result.outcome == "must_run_away"
```

- [ ] **Step 2: Run combat tests and confirm failure.** Implement strength calculation and help negotiation. Only the active player can invite one helper; accept only if the helper agrees to the recorded treasure or item terms. A hostile card modifies the current combat and invalidates a previously declared win.

```python
fighter_total = sum(combat_strength(state, user_id, catalog) for user_id in state.combat.fighter_ids)
monster_total = sum(catalog[card_id].bonus for card_id in state.combat.monster_ids)
monster_total += sum(catalog[card_id].bonus for card_id in state.combat.modifier_ids)
outcome = "provisional_win" if fighter_total > monster_total else "must_run_away"
if state.combat.helper_id is not None:
    raise RuleError("combat already has a helper")
```
- [ ] **Step 3: Add tests that reward cards stay pending until the entire fight ends, that solo treasure draw is private, that helped treasure is public, and that 10th level is granted only by killing a monster or an explicit card exception.** Implement `close_reaction` to settle combat only after all eligible players passed or the reaction deadline passed; a new legal card clears passes and creates a fresh deadline request for the adapter.

```python
eligible = set(state.order) - set(state.combat.fighter_ids)
if now < state.combat.reaction_deadline and not eligible.issubset(state.combat.passes):
    raise RuleError("reaction window is still open")
if declare_result(state, state.active_user_id, catalog).outcome != "provisional_win":
    raise RuleError("fighters are no longer winning")
state, reward_events = resolve_rewards(state, catalog)
```
- [ ] **Step 4: Add tests for escape rolls 4 (failure) and 5 (success), separate rolls against two monsters for both fighter and helper, a bad-stuff loss of an item, and death with corpse looting and next-turn restoration.** Implement rolls from the injected RNG and record each die result in a public event. Dead players keep level and eligible persistent identity cards; all other possessions follow the corpse-loot procedure.

```python
die = rng.randint(1, 6)
escaped = die + escape_modifier(state, actor_id, monster_id, catalog) >= 5
events.append(Event("group", "escape.rolled", {
    "user_id": actor_id, "monster_id": monster_id, "die": die, "escaped": escaped,
}))
if not escaped:
    state, bad_stuff_events = apply_bad_stuff(state, actor_id, monster_id, catalog)
    events.extend(bad_stuff_events)
```
- [ ] **Step 5: Run `python -m pytest tests/test_combat.py -q`; commit with `git commit -m "feat: resolve combat escape and death"`.**

### Task 6: Engine Routing, Visibility, and Replay Safety

**Files:**
- Create: `telegram-dota-dungeon/src/dota_dungeon/core/engine.py`
- Test: `telegram-dota-dungeon/tests/test_engine.py`
- Test: `telegram-dota-dungeon/tests/test_simulation.py`

**Interfaces:**
- Consumes: public rule functions from Tasks 2–5.
- Produces: `decide(state: GameState, command: Command, catalog: Catalog, rng: random.Random) -> tuple[GameState, list[Event]]`. `HANDLERS: dict[str, Callable]` and `ACTIVE_PLAYER_COMMANDS: set[str]` are defined in `engine.py`; `dispatch` is its private routing function. The Telegram/persistence plan calls only `decide`.

- [ ] **Step 1: Write an end-to-end test that issues join, ready, start, door, loot/seek-trouble, combat, charity and next-turn commands through `decide`.** Assert one public event for each public action and no hidden hand IDs in group events.
- [ ] **Step 2: Run `python -m pytest tests/test_engine.py -q` and confirm failure.** Route by an explicit command-name map; compare `command.actor_id` with the active player when required; reject unknown names and wrong `game_id`.

```python
if command.game_id != state.game_id:
    raise RuleError("command belongs to another game")
handler = HANDLERS.get(command.name)
if handler is None:
    raise RuleError("unknown command")
if command.name in ACTIVE_PLAYER_COMMANDS and command.actor_id != state.active_user_id:
    raise RuleError("not your turn")
new_state, events = handler(state, command, catalog, rng)
```
- [ ] **Step 3: Add replay tests.** Calling `decide` twice with the same `(game_id, request_id)` returns the previously recorded result or a no-op event without drawing, selling or transferring again. Store the processed request IDs in `GameState`; the persistence plan will keep this invariant inside a database transaction.

```python
if command.request_id in state.processed_requests:
    return state, []
new_state, events = dispatch(state, command, catalog, rng)
new_state.processed_requests.add(command.request_id)
return new_state, events
```
- [ ] **Step 4: Run the full suite with `python -m pytest -q`.** Add a deterministic two-player simulation that reaches a legal 10th-level monster kill and checks every physical card ID appears in exactly one zone after every command.
- [ ] **Step 5: Commit with `git commit -m "feat: expose replay-safe game engine"`.**

## Self-Review and Next Plans

This plan implements the reusable game engine with a small test catalog. It does not claim a public release. The remaining work is separated into two independently reviewable plans:

1. **Dota card catalog:** create the 168-row one-to-one mapping, write each thematic card description and effect definition, validate every repeated physical copy, price and special rule, and review asset rights.
2. **Telegram service and release:** connect group/private buttons to `decide`, persist the game with transactional locking and an outbox, run recoverable timers, and verify multiplayer scenarios in Telegram before public launch.

The engine plan's tests cover the five Review Focus conditions. Before its implementation is called complete, compare every engine rule in the spec with a named test, run the full suite, and review the diff. Later plans must reuse the exact `decide`, `Command`, `Event` and `Catalog` interfaces or revise this plan and its tests together.
