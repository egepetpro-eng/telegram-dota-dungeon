"""Turn phases and end-of-turn charity."""

from copy import deepcopy
from random import Random

from .effects import apply_effects
from .draw import draw_cards, legacy_catalog, resolve_pending_initial_triggers
from .model import Catalog, CombatState, Event, GameState, RuleError
from .character import effective_hand_limit, start_character_combat


def _require_active(state: GameState, actor_id: int, phase: str) -> None:
    if actor_id != state.active_user_id:
        raise RuleError("not your turn")
    if state.phase != phase:
        raise RuleError(f"action requires {phase}")


def open_door(
    state: GameState,
    actor_id: int,
    catalog: Catalog,
    rng: Random | None = None,
    *,
    resurrection_ids: list[str] | None = None,
    now=None,
) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.prepare")
    transition_rng = deepcopy(rng) if rng is not None else Random()
    result, events = resolve_pending_initial_triggers(state, catalog, transition_rng)
    if result.phase == "game.finished":
        if rng is not None:
            rng.setstate(transition_rng.getstate())
        return result, events
    result, draw_events = draw_cards(
        result,
        actor_id,
        "door",
        1,
        True,
        catalog,
        transition_rng,
        resurrection_ids=resurrection_ids,
    )
    events.extend(draw_events)
    result.phase = (
        "game.finished" if result.phase == "game.finished" else "turn.after_door"
    )
    drawn = next(
        (e.data["card_id"] for e in draw_events if e.name == "card.drawn"), None
    )
    if drawn is not None:
        card = catalog[drawn]
        events.append(Event("group", "door.revealed", {"card_id": drawn}))
        if drawn in result.players[actor_id].hand and not card.trigger:
            if card.kind == "monster":
                result.players[actor_id].hand.remove(drawn)
                result.phase = "combat.active"
                result.combat = CombatState(fighter_ids=[actor_id], monster_ids=[drawn])
                result.after_combat = False
                start_character_combat(result, catalog)
                from .combat import settle_mandatory_monsters

                result, ev = settle_mandatory_monsters(
                    result, catalog, transition_rng, now
                )
                events.extend(ev)
                from .trade import cancel_trades_for_combat

                events.extend(cancel_trades_for_combat(result, actor_id))
            elif card.kind == "curse" and any(
                c.rule_key == "wishing_ring" for c in catalog.values()
            ):
                from .decisions import start_curse

                result, ev = start_curse(
                    result, actor_id, actor_id, drawn, catalog, now, door=True
                )
                events.extend(ev)
            elif card.kind == "curse":
                # Reserve the exposed source while its effects draw cards.
                result, effect_events = apply_effects(
                    result,
                    actor_id,
                    card.effects,
                    catalog,
                    choices={"played_card_id": drawn, "actor_id": actor_id},
                    rng=transition_rng,
                )
                events.extend(effect_events)
                if drawn in result.players[actor_id].hand:
                    result.players[actor_id].hand.remove(drawn)
                    result.door_discard.append(drawn)
                events.append(
                    Event(
                        "group",
                        "curse.applied",
                        {"card_id": drawn, "target_id": actor_id},
                    )
                )
    if rng is not None:
        rng.setstate(transition_rng.getstate())
    return result, events


def seek_trouble(
    state: GameState,
    actor_id: int,
    card_id: str,
    catalog: Catalog,
    *,
    now=None,
    rng=None,
) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.after_door")
    if (
        card_id not in state.players[actor_id].hand
        or catalog[card_id].kind != "monster"
    ):
        raise RuleError("monster must be in your hand")
    result = deepcopy(state)
    result.players[actor_id].hand.remove(card_id)
    result.combat = CombatState(fighter_ids=[actor_id], monster_ids=[card_id])
    result.after_combat = False
    start_character_combat(result, catalog)
    result.phase = "combat.active"
    from .trade import cancel_trades_for_combat

    events = [
        Event(
            "group",
            "combat.started",
            {"monster_ids": [card_id], "fighter_id": actor_id},
        )
    ]
    events.extend(cancel_trades_for_combat(result, actor_id))
    from .combat import settle_mandatory_monsters

    result, ev = settle_mandatory_monsters(result, catalog, rng or Random(), now)
    return result, events + ev


def loot_room(
    state: GameState,
    actor_id: int,
    rng: Random | None = None,
    *,
    catalog: Catalog | None = None,
) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.after_door")
    transition_rng = deepcopy(rng) if rng is not None else Random()
    result, events = draw_cards(
        state,
        actor_id,
        "door",
        1,
        False,
        catalog if catalog is not None else legacy_catalog(state),
        transition_rng,
    )
    if result.phase != "game.finished":
        result.phase = "turn.charity"
    events.append(Event("group", "room.looted", {"user_id": actor_id}))
    if rng is not None:
        rng.setstate(transition_rng.getstate())
    return result, events


def charity_recipients(state):
    """Living lowest-level recipients, shared by commands and private menus."""
    living = [u for u in state.order if state.players[u].alive]
    if not living:
        return []
    minimum = min(state.players[u].level for u in living)
    return [u for u in living if state.players[u].level == minimum]


def give_charity(
    state: GameState,
    actor_id: int,
    assignments: dict[int, list[str]],
    catalog: Catalog | None = None,
    *, discard_ids: list[str] | None = None,
) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.charity")
    result = deepcopy(state)
    player = result.players[actor_id]
    excess = max(
        0,
        len(player.hand)
        - (
            effective_hand_limit(state, actor_id, catalog) if catalog is not None else 5
        ),
    )
    if not excess:
        if any(assignments.values()) or discard_ids:
            raise RuleError("no excess cards")
        return result, []
    recipients = set(charity_recipients(state))
    if actor_id in recipients:
        if assignments:
            raise RuleError("lowest level discards excess")
        cards = discard_ids
        if (not isinstance(cards, list) or len(cards) != excess
                or len(set(cards)) != excess or not set(cards).issubset(player.hand)):
            raise RuleError("charity discards must match excess")
        for card_id in cards:
            player.hand.remove(card_id)
            deck = result.card_decks.get(card_id)
            if deck is None:
                raise RuleError("unknown card deck")
            (result.door_discard if deck == "door" else result.treasure_discard).append(card_id)
        return result, [
            Event("group", "charity.discarded", {"user_id": actor_id, "count": excess})
        ]
    if discard_ids:
        raise RuleError("charity must go to lowest-level players")
    if set(assignments) != recipients:
        raise RuleError("charity must go to lowest-level players")
    cards = [card_id for group in assignments.values() for card_id in group]
    if (
        len(cards) != excess
        or len(set(cards)) != excess
        or not set(cards).issubset(player.hand)
    ):
        raise RuleError("charity cards do not match excess")
    counts = [len(group) for group in assignments.values()]
    if max(counts) - min(counts) > 1:
        raise RuleError("charity must be evenly distributed")
    for recipient, group in assignments.items():
        for card_id in group:
            player.hand.remove(card_id)
            result.players[recipient].hand.append(card_id)
    return result, [
        Event(
            "group",
            "charity.given",
            {"from": actor_id, "counts": {u: len(v) for u, v in assignments.items()}},
        )
    ]


def end_turn(
    state: GameState,
    actor_id: int,
    rng: Random | None = None,
    *,
    catalog: Catalog | None = None,
) -> tuple[GameState, list[Event]]:
    _require_active(state, actor_id, "turn.charity")
    if (
        state.players[actor_id].pending_big_excess
        or state.players[actor_id].pending_identity_excess
    ):
        raise RuleError("resolve excess Big Items first")
    if any(cards and any(state.players[u].alive for u in state.corpse_loot_order.get(uid, []))
           for uid, cards in state.corpse.items()):
        raise RuleError("resolve corpse loot before the next turn")
    if len(state.players[actor_id].hand) > (
        effective_hand_limit(state, actor_id, catalog) if catalog is not None else 5
    ):
        raise RuleError("hand cannot exceed five cards (six for Dwarf)")
    result = deepcopy(state)
    transition_rng = deepcopy(rng) if rng is not None else Random()
    index = result.order.index(actor_id)
    result.active_user_id = result.order[(index + 1) % len(result.order)]
    result.turn_number += 1
    result.after_combat = False
    result.phase = "turn.prepare"
    next_player = result.players[result.active_user_id]
    events = [Event("group", "turn.started", {"user_id": result.active_user_id})]
    # Revival and replacement cards have different deadlines. Legacy dead states
    # also acquire the entitlement here when first loaded with the new model.
    for uid in result.order:
        p = result.players[uid]
        if p.alive:
            continue
        p.alive = True
        p.rebirth_pending = True
        for cid in result.corpse.pop(uid, []):
            getattr(result, f"{result.card_decks[cid]}_discard").append(cid)
        result.corpse_looted_by.pop(uid, None)
        result.corpse_hand.pop(uid, None)
        result.corpse_loot_order.pop(uid, None)
        events.append(Event("group", "player.revived", {"user_id": uid}))
    if next_player.rebirth_pending:
        next_player.rebirth_pending = False
        for deck in ("door", "treasure"):
            result, drawn_events = draw_cards(
                result,
                next_player.user_id,
                deck,
                4,
                False,
                catalog if catalog is not None else legacy_catalog(result),
                transition_rng,
            )
            events.extend(drawn_events)
        next_player = result.players[result.active_user_id]
        events.append(
            Event(
                f"user:{next_player.user_id}",
                "player.reborn",
                {"card_ids": next_player.hand.copy()},
            )
        )
    if rng is not None:
        rng.setstate(transition_rng.getstate())
    return result, events
