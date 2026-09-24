"""Declarative card effects. Only catalog-listed operations are executable."""

from copy import deepcopy

from .catalog import EFFECTS
from .model import Catalog, Event, GameState, RuleError


def apply_effects(state: GameState, target_id: int, effects: list[dict],
                  catalog: Catalog) -> tuple[GameState, list[Event]]:
    if target_id not in state.players:
        raise RuleError("unknown target")
    for effect in effects:
        if effect.get("op") not in EFFECTS:
            raise RuleError("unknown effect")
    result = deepcopy(state)
    player = result.players[target_id]
    events: list[Event] = []
    for effect in effects:
        op = effect["op"]
        amount = effect.get("amount", 1)
        if op == "gain_level":
            if player.level + amount >= 10 and not effect.get("can_win", False):
                raise RuleError("effect cannot grant winning level")
            player.level += amount
        elif op == "lose_level":
            player.level = max(1, player.level - amount)
        elif op == "add_strength":
            if result.combat:
                result.combat.temporary_strength[target_id] = result.combat.temporary_strength.get(target_id, 0) + amount
            else:
                player.strength_bonus += amount
        elif op == "escape_modifier":
            player.escape_bonus += amount
        elif op == "monster_modifier":
            if not result.combat:
                raise RuleError("no active combat")
            result.combat.monster_strength_bonus += amount
        elif op == "prevent_bad_stuff":
            if not result.combat:
                raise RuleError("no active combat")
            result.combat.prevented_bad_stuff.add((target_id, effect["monster_id"]))
        elif op == "remove_item":
            from .items import remove_owned_card
            card_id = effect["card_id"]
            remove_owned_card(player, card_id)
            result.treasure_discard.append(card_id)
        elif op == "draw":
            deck = effect.get("deck", "treasure")
            stack = result.door_deck if deck == "door" else result.treasure_deck
            if not stack:
                raise RuleError("deck is empty")
            for _ in range(amount):
                player.hand.append(stack.pop())
            events.append(Event(f"user:{target_id}", "card.drawn", {"count": amount}))
        elif op in {"kill_monster", "remove_monster"}:
            if not result.combat:
                raise RuleError("no active combat")
            monster_id = effect["monster_id"]
            result.combat.monster_ids.remove(monster_id)
            result.door_discard.append(monster_id)
        elif op == "persistent":
            card_id = effect["card_id"]
            if card_id not in player.in_play:
                player.in_play.append(card_id)
        events.append(Event("group", "effect.applied", {"target_id": target_id, "op": op}))
    return result, events
