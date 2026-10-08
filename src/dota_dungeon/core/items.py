"""Open possessions, equipment slots and sale of item value for levels."""

from copy import deepcopy

from .model import Catalog, Event, GameState, Player, RuleError


def _outside_combat(state: GameState) -> None:
    if state.combat is not None or state.phase in {"combat.active", "combat.run_away"}:
        raise RuleError("cannot change equipment in combat")


def _check_slots(player: Player, card_id: str, catalog: Catalog) -> None:
    slot = catalog[card_id].slots
    occupied = [catalog[item].slots for item in player.equipped]
    if slot in {"head", "armor", "footwear"} and slot in occupied:
        raise RuleError(f"{slot} slot is occupied")
    if slot == "two_hands" and any(s in {"one_hand", "two_hands"} for s in occupied):
        raise RuleError("hand slots are occupied")
    if slot == "one_hand" and ("two_hands" in occupied or occupied.count("one_hand") >= 2):
        raise RuleError("hand slots are occupied")


def can_use(player: Player, card_id: str, catalog: Catalog) -> bool:
    restrictions = catalog[card_id].restrictions
    roles = {catalog[cid].rule_key for cid in player.role_ids}
    races = {catalog[cid].rule_key for cid in player.race_ids}
    for key, identities in (("role_any", roles), ("race_any", races)):
        if restrictions.get(key) and not identities.intersection(restrictions[key]):
            return False
    if roles.intersection(restrictions.get("cannot_use_roles", [])) or races.intersection(restrictions.get("cannot_use_races", [])):
        return False
    if "sex" in restrictions and getattr(player, "sex", None) != restrictions["sex"]:
        return False
    required = restrictions.get("requires_rule")
    return not required or any(catalog[cid].rule_key == required for cid in player.in_play)


def reconcile_equipment(player: Player, catalog: Catalog) -> None:
    player.equipped[:] = [cid for cid in player.equipped if can_use(player, cid, catalog)]


def carry(state: GameState, actor_id: int, card_id: str,
          catalog: Catalog) -> tuple[GameState, list[Event]]:
    _outside_combat(state)
    if state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"}:
        raise RuleError("item cannot be carried in this phase")
    if actor_id != state.active_user_id and (state.phase != "turn.prepare" or state.turn_number > 1):
        raise RuleError("not your turn")
    if actor_id not in state.players or card_id not in state.players[actor_id].hand:
        raise RuleError("item is not in hand")
    card = catalog[card_id]
    if card.kind != "item":
        raise RuleError("only items can be carried")
    player = state.players[actor_id]
    if card.size == "big" and any(catalog[cid].size == "big" for cid in player.in_play):
        raise RuleError("only one Big item can be carried")
    result = deepcopy(state)
    result.players[actor_id].hand.remove(card_id)
    result.players[actor_id].in_play.append(card_id)
    return result, [Event("group", "item.carried", {"user_id": actor_id, "card_id": card_id})]


def equip(state: GameState, actor_id: int, card_id: str,
          catalog: Catalog) -> tuple[GameState, list[Event]]:
    _outside_combat(state)
    if actor_id not in state.players:
        raise RuleError("unknown player")
    player = state.players[actor_id]
    if card_id not in player.hand and card_id not in player.in_play:
        raise RuleError("item is not owned")
    if card_id in player.equipped:
        raise RuleError("item already equipped")
    card = catalog[card_id]
    if card.kind != "item":
        raise RuleError("only items can be equipped")
    if state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"}:
        raise RuleError("equipment cannot change in this phase")
    if not can_use(player, card_id, catalog):
        raise RuleError("item identity restriction")
    _check_slots(player, card_id, catalog)
    if card.size == "big" and card_id in player.hand:
        if sum(catalog[item].size == "big" for item in player.in_play) >= 1:
            raise RuleError("only one Big item can be carried")
    result = deepcopy(state)
    owner = result.players[actor_id]
    if card_id in owner.hand:
        owner.hand.remove(card_id)
        owner.in_play.append(card_id)
    owner.equipped.append(card_id)
    return result, [Event("group", "item.equipped", {"user_id": actor_id, "card_id": card_id})]


def unequip(state: GameState, actor_id: int, card_id: str) -> tuple[GameState, list[Event]]:
    _outside_combat(state)
    if actor_id not in state.players or card_id not in state.players[actor_id].equipped:
        raise RuleError("item is not equipped")
    result = deepcopy(state)
    result.players[actor_id].equipped.remove(card_id)
    return result, [Event("group", "item.unequipped", {"user_id": actor_id, "card_id": card_id})]


def play_identity(state: GameState, actor_id: int, card_id: str,
                  catalog: Catalog) -> tuple[GameState, list[Event]]:
    if (actor_id not in state.players or state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"}
            or (actor_id != state.active_user_id and (state.phase != "turn.prepare" or state.turn_number > 1))):
        raise RuleError("identity can be played only on your turn")
    _outside_combat(state)
    if card_id not in state.players[actor_id].hand:
        raise RuleError("identity card is not in hand")
    card = catalog[card_id]
    if card.kind not in {"role", "race"}:
        raise RuleError("card is not a role or race")
    result = deepcopy(state)
    player = result.players[actor_id]
    active = player.role_ids if card.kind == "role" else player.race_ids
    if active:
        old_id = active.pop()
        player.in_play.remove(old_id)
        result.door_discard.append(old_id)
    player.hand.remove(card_id)
    player.in_play.append(card_id)
    active.append(card_id)
    reconcile_equipment(player, catalog)
    return result, [Event("group", "identity.played", {
        "user_id": actor_id, "card_id": card_id, "kind": card.kind})]


def remove_owned_card(player: Player, card_id: str) -> None:
    if card_id in player.hand:
        player.hand.remove(card_id)
    elif card_id in player.in_play:
        player.in_play.remove(card_id)
        if card_id in player.equipped:
            player.equipped.remove(card_id)
        if card_id in player.role_ids:
            player.role_ids.remove(card_id)
        if card_id in player.race_ids:
            player.race_ids.remove(card_id)
    else:
        raise RuleError("card is not owned")


def sell(state: GameState, actor_id: int, card_ids: list[str],
         catalog: Catalog) -> tuple[GameState, list[Event]]:
    if actor_id != state.active_user_id or state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"} or state.combat:
        raise RuleError("sale is allowed only on your turn outside combat")
    player = state.players[actor_id]
    if not card_ids or len(card_ids) != len(set(card_ids)):
        raise RuleError("select distinct items")
    if any(cid not in player.hand and cid not in player.in_play for cid in card_ids):
        raise RuleError("item is not owned")
    if any(catalog[cid].kind != "item" for cid in card_ids):
        raise RuleError("only items can be sold")
    gained = sum(catalog[cid].value for cid in card_ids) // 1000
    if gained < 1:
        raise RuleError("sale requires 1000 gold value")
    if player.level + gained >= 10:
        raise RuleError("sale cannot grant the winning level")
    result = deepcopy(state)
    for cid in card_ids:
        remove_owned_card(result.players[actor_id], cid)
        result.treasure_discard.append(cid)
    from .trade import cancel_trades_for_cards
    cancel_trades_for_cards(result, card_ids)
    result.players[actor_id].level += gained
    return result, [Event("group", "items.sold", {"user_id": actor_id, "card_ids": card_ids.copy(), "levels": gained})]
