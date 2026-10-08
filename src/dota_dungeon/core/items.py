"""Open possessions, equipment slots and sale of item value for levels."""

from copy import deepcopy

from .model import CardDef, Catalog, Event, GameState, Player, RuleError
from .character import identities, has_rule, no_disadvantages


def is_item_card(card: CardDef) -> bool:
    return card.kind == "item" or (
        card.kind == "one_shot"
        and (card.value > 0 or card.rule_key == "pretty_balloons")
    )


def ignored_item(player: Player, card_id: str) -> bool:
    return (
        card_id in player.attachments.values()
        or card_id in player.hireling_items.values()
    )


def big_count(player: Player, catalog: Catalog, card_ids=None) -> int:
    return sum(
        is_item_card(catalog[cid])
        and catalog[cid].size == "big"
        and not ignored_item(player, cid)
        for cid in (player.in_play if card_ids is None else card_ids)
    )


def big_limit(player: Player, catalog: Catalog):
    return None if "dwarf" in identities(player, catalog, "race") else 1


def _outside_combat(state: GameState) -> None:
    if state.combat is not None or state.phase in {"combat.active", "combat.run_away"}:
        raise RuleError("cannot change equipment in combat")


def _check_slots(player: Player, card_id: str, catalog: Catalog) -> None:
    if ignored_item(player, card_id):
        return
    slot = catalog[card_id].slots
    occupied = [
        catalog[item].slots
        for item in player.equipped
        if not ignored_item(player, item)
    ]
    if slot in {"head", "armor", "footwear"} and slot in occupied:
        raise RuleError(f"{slot} slot is occupied")
    if slot == "two_hands" and any(s in {"one_hand", "two_hands"} for s in occupied):
        raise RuleError("hand slots are occupied")
    if slot == "one_hand" and (
        "two_hands" in occupied or occupied.count("one_hand") >= 2
    ):
        raise RuleError("hand slots are occupied")


def can_use(player: Player, card_id: str, catalog: Catalog) -> bool:
    if ignored_item(player, card_id):
        return True
    restrictions = catalog[card_id].restrictions
    roles = identities(player, catalog, "role")
    races = identities(player, catalog, "race")
    for key, active_identities in (("role_any", roles), ("race_any", races)):
        if restrictions.get(key) and not active_identities.intersection(
            restrictions[key]
        ):
            return False
    if (
        roles.intersection(restrictions.get("cannot_use_roles", []))
        and not no_disadvantages(player, catalog, "role")
    ) or (
        races.intersection(restrictions.get("cannot_use_races", []))
        and not no_disadvantages(player, catalog, "race")
    ):
        return False
    if "sex" in restrictions and player.character_sex != restrictions["sex"]:
        return False
    required = restrictions.get("requires_rule")
    return not required or any(
        catalog[cid].rule_key == required for cid in player.in_play
    )


def reconcile_equipment(player: Player, catalog: Catalog) -> None:
    player.equipped[:] = [cid for cid in player.equipped if can_use(player, cid, catalog)]


def carry(
    state: GameState, actor_id: int, card_id: str, catalog: Catalog
) -> tuple[GameState, list[Event]]:
    _outside_combat(state)
    if state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"}:
        raise RuleError("item cannot be carried in this phase")
    if actor_id not in state.players or card_id not in state.players[actor_id].hand:
        raise RuleError("item is not in hand")
    card = catalog[card_id]
    if not is_item_card(card):
        raise RuleError("only items can be carried")
    player = state.players[actor_id]
    if (
        card.size == "big"
        and big_limit(player, catalog) is not None
        and big_count(player, catalog) >= big_limit(player, catalog)
    ):
        raise RuleError("only one Big item can be carried")
    result = deepcopy(state)
    result.players[actor_id].hand.remove(card_id)
    result.players[actor_id].in_play.append(card_id)
    return result, [
        Event("group", "item.carried", {"user_id": actor_id, "card_id": card_id})
    ]


def equip(
    state: GameState, actor_id: int, card_id: str, catalog: Catalog
) -> tuple[GameState, list[Event]]:
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
    if (
        card.size == "big"
        and card_id in player.hand
        and not ignored_item(player, card_id)
    ):
        if big_limit(player, catalog) is not None and big_count(
            player, catalog
        ) >= big_limit(player, catalog):
            raise RuleError("only one Big item can be carried")
    result = deepcopy(state)
    owner = result.players[actor_id]
    if card_id in owner.hand:
        owner.hand.remove(card_id)
        owner.in_play.append(card_id)
    owner.equipped.append(card_id)
    return result, [
        Event("group", "item.equipped", {"user_id": actor_id, "card_id": card_id})
    ]


def unequip(state: GameState, actor_id: int, card_id: str) -> tuple[GameState, list[Event]]:
    _outside_combat(state)
    if actor_id not in state.players or card_id not in state.players[actor_id].equipped:
        raise RuleError("item is not equipped")
    result = deepcopy(state)
    result.players[actor_id].equipped.remove(card_id)
    return result, [Event("group", "item.unequipped", {"user_id": actor_id, "card_id": card_id})]


def play_identity(
    state: GameState, actor_id: int, card_id: str, catalog: Catalog
) -> tuple[GameState, list[Event]]:
    if (
        actor_id not in state.players
        or state.phase
        not in {
            "turn.prepare",
            "turn.after_door",
            "turn.charity",
            "combat.active",
            "combat.run_away",
        }
        or (
            actor_id != state.active_user_id
            and (state.phase != "turn.prepare" or state.turn_number > 1)
        )
    ):
        raise RuleError("identity can be played only on your turn")
    if card_id not in state.players[actor_id].hand:
        raise RuleError("identity card is not in hand")
    card = catalog[card_id]
    if card.kind not in {"role", "race"}:
        raise RuleError("card is not a role or race")
    result = deepcopy(state)
    player = result.players[actor_id]
    active = player.role_ids if card.kind == "role" else player.race_ids
    if any(catalog[cid].rule_key == card.rule_key for cid in active) and card.rule_key:
        raise RuleError("duplicate identity")
    limit = (
        2
        if has_rule(
            player, catalog, "super_munchkin" if card.kind == "role" else "half_breed"
        )
        else 1
    )
    if len(active) >= limit:
        old_id = active.pop()
        player.in_play.remove(old_id)
        result.door_discard.append(old_id)
    player.hand.remove(card_id)
    player.in_play.append(card_id)
    active.append(card_id)
    reconcile_possessions(result, actor_id, catalog)
    return result, [
        Event(
            "group",
            "identity.played",
            {"user_id": actor_id, "card_id": card_id, "kind": card.kind},
        )
    ]


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


def sell(
    state: GameState, actor_id: int, card_ids: list[str], catalog: Catalog
) -> tuple[GameState, list[Event]]:
    if (
        actor_id != state.active_user_id
        or state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"}
        or state.combat
    ):
        raise RuleError("sale is allowed only on your turn outside combat")
    player = state.players[actor_id]
    if not card_ids or len(card_ids) != len(set(card_ids)):
        raise RuleError("select distinct items")
    if any(cid not in player.hand and cid not in player.in_play for cid in card_ids):
        raise RuleError("item is not owned")
    if any(not is_item_card(catalog[cid]) for cid in card_ids):
        raise RuleError("only items can be sold")
    double = (
        "halfling" in identities(player, catalog, "race")
        and player.halfling_sale_turn != state.turn_number
    )
    if player.pending_big_excess and not any(
        cid in player.in_play
        and catalog[cid].size == "big"
        and not ignored_item(player, cid)
        for cid in card_ids
    ):
        raise RuleError("sale must remove excess Big Items")
    gained = (
        sum(catalog[cid].value for cid in card_ids)
        + (catalog[card_ids[0]].value if double else 0)
    ) // 1000
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
    if double:
        result.players[actor_id].halfling_sale_turn = result.turn_number
    reconcile_possessions(result, actor_id, catalog)
    result.players[actor_id].level += gained
    return result, [
        Event(
            "group",
            "items.sold",
            {"user_id": actor_id, "card_ids": card_ids.copy(), "levels": gained},
        )
    ]


def reconcile_possessions(state: GameState, user_id: int, catalog: Catalog) -> None:
    """Reconcile references and source-dependent losses, preserving physical zones."""
    p = state.players[user_id]

    def discard(cid):
        if cid in p.in_play or cid in p.hand:
            remove_owned_card(p, cid)
            getattr(state, f"{catalog[cid].deck}_discard").append(cid)
            from .trade import cancel_trades_for_cards

            cancel_trades_for_cards(state, [cid])

    for attachment, item in list(p.attachments.items()):
        if attachment not in p.in_play or item not in p.in_play:
            discard(attachment)
            del p.attachments[attachment]
    for hireling, item in list(p.hireling_items.items()):
        if hireling not in p.in_play:
            discard(item)
            del p.hireling_items[hireling]
        elif item not in p.in_play:
            del p.hireling_items[hireling]
    for kind, enabler in [("role", "super_munchkin"), ("race", "half_breed")]:
        active = p.role_ids if kind == "role" else p.race_ids
        for cid in list(p.in_play):
            if catalog[cid].rule_key == enabler and not active:
                discard(cid)
        excess = max(0, len(active) - (2 if has_rule(p, catalog, enabler) else 1))
        if excess:
            p.pending_identity_excess[kind] = excess
        else:
            p.pending_identity_excess.pop(kind, None)
    reconcile_equipment(p, catalog)
    limit = big_limit(p, catalog)
    p.pending_big_excess = (
        max(0, big_count(p, catalog) - limit) if limit is not None else 0
    )


def assign_hireling(
    state: GameState, actor_id: int, hireling_id: str, card_id: str, catalog: Catalog
):
    _outside_combat(state)
    if state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"}:
        raise RuleError("cannot assign hireling now")
    p = state.players[actor_id]
    if hireling_id not in p.in_play or catalog[hireling_id].rule_key != "hireling":
        raise RuleError("no carried hireling")
    if card_id not in p.hand + p.in_play or catalog[card_id].kind != "item":
        raise RuleError("hireling requires owned equipment Item")
    result = deepcopy(state)
    p = result.players[actor_id]
    former_item = p.hireling_items.get(hireling_id)
    if former_item in p.equipped:
        p.equipped.remove(former_item)
    if card_id in p.hand:
        p.hand.remove(card_id)
        p.in_play.append(card_id)
    if card_id in p.equipped:
        p.equipped.remove(card_id)
    p.hireling_items[hireling_id] = card_id
    reconcile_possessions(result, actor_id, catalog)
    return result, [
        Event(
            "group",
            "hireling.item_assigned",
            {"user_id": actor_id, "hireling_id": hireling_id, "card_id": card_id},
        )
    ]


def discard_identity(state: GameState, actor_id: int, card_id: str, catalog: Catalog):
    if state.phase in {"lobby", "game.finished"}:
        raise RuleError("identity cannot be discarded now")
    p = state.players.get(actor_id)
    if (
        p is None
        or card_id not in p.in_play
        or (
            card_id not in p.role_ids + p.race_ids
            and catalog[card_id].rule_key not in {"half_breed", "super_munchkin"}
        )
    ):
        raise RuleError("identity is not in play")
    result = deepcopy(state)
    remove_owned_card(result.players[actor_id], card_id)
    getattr(result, f"{catalog[card_id].deck}_discard").append(card_id)
    reconcile_possessions(result, actor_id, catalog)
    return result, [
        Event("group", "identity.discarded", {"user_id": actor_id, "card_id": card_id})
    ]


def resolve_big_items(
    state: GameState,
    actor_id: int,
    card_ids: list[str],
    catalog: Catalog,
    recipient_id=None,
):
    p = state.players.get(actor_id)
    if p is None or not p.pending_big_excess:
        raise RuleError("no excess Big Items")
    if (
        not card_ids
        or len(card_ids) > p.pending_big_excess
        or len(set(card_ids)) != len(card_ids)
    ):
        raise RuleError("choose excess Big Items")
    if any(
        cid not in p.in_play
        or catalog[cid].size != "big"
        or not is_item_card(catalog[cid])
        or ignored_item(p, cid)
        for cid in card_ids
    ):
        raise RuleError("invalid excess Item choice")
    eligible = {
        uid
        for uid, q in state.players.items()
        if uid != actor_id
        and q.alive
        and (
            big_limit(q, catalog) is None
            or big_count(q, catalog) < big_limit(q, catalog)
        )
    }
    if recipient_id is None:
        if eligible:
            raise RuleError("excess Big Items must go to lowest eligible players")
        if len(card_ids) != p.pending_big_excess:
            raise RuleError("discard exact excess Big Items")
    else:
        if (
            type(recipient_id) is not int
            or recipient_id not in eligible
            or state.players[recipient_id].level
            != min(state.players[uid].level for uid in eligible)
        ):
            raise RuleError("recipient must be lowest eligible player")
        limit = big_limit(state.players[recipient_id], catalog)
        if (
            limit is not None
            and big_count(state.players[recipient_id], catalog) + len(card_ids) > limit
        ):
            raise RuleError("recipient Big Item capacity exceeded")
    result = deepcopy(state)
    from .character import discard_cards

    if recipient_id is None:
        discard_cards(result, actor_id, card_ids, catalog)
    else:
        for cid in card_ids:
            remove_owned_card(result.players[actor_id], cid)
            result.players[recipient_id].in_play.append(cid)
        reconcile_possessions(result, actor_id, catalog)
        from .trade import cancel_trades_for_cards

        cancel_trades_for_cards(result, card_ids)
    return result, [
        Event(
            "group",
            "items.excess_resolved",
            {"user_id": actor_id, "card_ids": card_ids, "recipient_id": recipient_id},
        )
    ]


def resolve_identity_excess(
    state: GameState, actor_id: int, card_ids: list[str], catalog: Catalog
):
    p = state.players.get(actor_id)
    if p is None or not p.pending_identity_excess:
        raise RuleError("no excess identities")
    if len(set(card_ids)) != len(card_ids) or any(
        cid not in p.role_ids + p.race_ids for cid in card_ids
    ):
        raise RuleError("invalid identity choices")
    counts = {
        kind: sum(catalog[cid].kind == kind for cid in card_ids)
        for kind in p.pending_identity_excess
    }
    if counts != p.pending_identity_excess or len(card_ids) != sum(counts.values()):
        raise RuleError("choose exact excess identities")
    result = deepcopy(state)
    from .character import discard_cards

    discard_cards(result, actor_id, card_ids, catalog)
    return result, [
        Event(
            "group",
            "identity.excess_resolved",
            {"user_id": actor_id, "card_ids": card_ids},
        )
    ]
