"""Turn phases and end-of-turn charity."""

from copy import deepcopy
from random import Random

from .effects import apply_effects
from .model import Catalog, CombatState, Event, GameState, RuleError


def _require_active(state: GameState, actor_id: int, phase: str) -> None:
    if actor_id != state.active_user_id:
        raise RuleError("not your turn")
    if state.phase != phase:
        raise RuleError(f"action requires {phase}")


def _draw_door(state: GameState, rng: Random | None) -> str:
    if not state.door_deck:
        if not state.door_discard:
            raise RuleError("door deck is empty")
        state.door_deck = state.door_discard
        state.door_discard = []
        (rng or Random()).shuffle(state.door_deck)
    return state.door_deck.pop()


def open_door(state: GameState, actor_id: int, catalog: Catalog,
              rng: Random | None = None) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.prepare")
    if not state.door_deck and not state.door_discard:
        raise RuleError("door deck is empty")
    result = deepcopy(state)
    card_id = _draw_door(result, rng)
    card = catalog[card_id]
    events = [Event("group", "door.revealed", {"card_id": card_id})]
    if card.kind == "monster":
        result.phase = "combat.active"
        result.combat = CombatState(fighter_ids=[actor_id], monster_ids=[card_id])
        from .trade import cancel_trades_for_combat
        events.extend(cancel_trades_for_combat(result, actor_id))
    elif card.kind == "curse":
        result.phase = "turn.after_door"
        result.door_discard.append(card_id)
        result, effect_events = apply_effects(result, actor_id, card.effects, catalog)
        events.extend(effect_events)
        events.append(Event("group", "curse.applied", {"card_id": card_id, "target_id": actor_id}))
    else:
        result.phase = "turn.after_door"
        result.players[actor_id].hand.append(card_id)
    return result, events


def seek_trouble(state: GameState, actor_id: int, card_id: str,
                 catalog: Catalog) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.after_door")
    if card_id not in state.players[actor_id].hand or catalog[card_id].kind != "monster":
        raise RuleError("monster must be in your hand")
    result = deepcopy(state)
    result.players[actor_id].hand.remove(card_id)
    result.combat = CombatState(fighter_ids=[actor_id], monster_ids=[card_id])
    result.phase = "combat.active"
    from .trade import cancel_trades_for_combat
    events = [Event("group", "combat.started", {"monster_ids": [card_id], "fighter_id": actor_id})]
    events.extend(cancel_trades_for_combat(result, actor_id))
    return result, events


def loot_room(state: GameState, actor_id: int, rng: Random | None = None) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.after_door")
    if not state.door_deck and not state.door_discard:
        raise RuleError("door deck is empty")
    result = deepcopy(state)
    card_id = _draw_door(result, rng)
    result.players[actor_id].hand.append(card_id)
    result.phase = "turn.charity"
    return result, [Event("actor", "card.drawn", {"card_id": card_id}),
                    Event("group", "room.looted", {"user_id": actor_id})]


def give_charity(state: GameState, actor_id: int,
                 assignments: dict[int, list[str]]) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.charity")
    result = deepcopy(state)
    player = result.players[actor_id]
    excess = max(0, len(player.hand) - 5)
    if not excess:
        if any(assignments.values()):
            raise RuleError("no excess cards")
        return result, []
    minimum = min(p.level for p in result.players.values())
    if player.level == minimum:
        if any(assignments.values()):
            raise RuleError("lowest level discards excess")
        cards = player.hand[-excess:]
        del player.hand[-excess:]
        for card_id in cards:
            deck = result.card_decks.get(card_id)
            if deck is None:
                raise RuleError("unknown card deck")
            (result.door_discard if deck == "door" else result.treasure_discard).append(card_id)
        return result, [Event("group", "charity.discarded", {"user_id": actor_id, "count": excess})]
    recipients = {u for u, p in result.players.items() if p.level == minimum}
    if set(assignments) != recipients or any(not cards for cards in assignments.values()):
        raise RuleError("charity must go to lowest-level players")
    cards = [card_id for group in assignments.values() for card_id in group]
    if len(cards) != excess or len(set(cards)) != excess or not set(cards).issubset(player.hand):
        raise RuleError("charity cards do not match excess")
    counts = [len(group) for group in assignments.values()]
    if max(counts) - min(counts) > 1:
        raise RuleError("charity must be evenly distributed")
    for recipient, group in assignments.items():
        for card_id in group:
            player.hand.remove(card_id)
            result.players[recipient].hand.append(card_id)
    return result, [Event("group", "charity.given", {"from": actor_id, "counts": {u: len(v) for u, v in assignments.items()}})]


def _draw_for_rebirth(state: GameState, deck: str, rng: Random | None) -> str:
    stack = state.door_deck if deck == "door" else state.treasure_deck
    discard = state.door_discard if deck == "door" else state.treasure_discard
    if not stack:
        if not discard:
            raise RuleError(f"{deck} deck is empty")
        stack.extend(discard)
        discard.clear()
        (rng or Random()).shuffle(stack)
    return stack.pop()


def end_turn(state: GameState, actor_id: int,
             rng: Random | None = None) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.charity")
    if len(state.players[actor_id].hand) > 5:
        raise RuleError("hand cannot exceed five cards")
    result = deepcopy(state)
    index = result.order.index(actor_id)
    result.active_user_id = result.order[(index + 1) % len(result.order)]
    result.turn_number += 1
    result.phase = "turn.prepare"
    next_player = result.players[result.active_user_id]
    events = [Event("group", "turn.started", {"user_id": result.active_user_id})]
    if not next_player.alive:
        for cid in result.corpse.pop(next_player.user_id, []):
            deck = result.card_decks[cid]
            (result.door_discard if deck == "door" else result.treasure_discard).append(cid)
        result.corpse_looted_by.pop(next_player.user_id, None)
        result.corpse_hand.pop(next_player.user_id, None)
        next_player.hand.extend(_draw_for_rebirth(result, "door", rng) for _ in range(4))
        next_player.hand.extend(_draw_for_rebirth(result, "treasure", rng) for _ in range(4))
        next_player.alive = True
        events.append(Event(f"user:{next_player.user_id}", "player.reborn", {
            "card_ids": next_player.hand.copy()}))
    return result, events
