"""Source-verified mandatory acquisition handlers; no registry dependencies."""

from copy import deepcopy

from .model import Event


def _exact(args: dict, expected: dict) -> None:
    if not isinstance(args, dict) or set(args) != set(expected):
        raise ValueError("unexpected rule arguments")
    if any(
        type(args[key]) is not type(value) or args[key] != value
        for key, value in expected.items()
    ):
        raise ValueError("arguments do not match the implemented source rule")


def _mandatory_args(args):
    _exact(args, {})


def _hoard_args(args):
    _exact(args, {"include_initial_deal": True})


def _cleric_args(args):
    _exact(args, {"amount": 1, "can_win": True, "alert_if_in_hand": True})


def all_clerics_gain_level(state, target_id, args, catalog, *, choices, rng):
    """Divine Intervention affects active Clerics, and may grant victory."""
    _cleric_args(args)
    result = deepcopy(state)
    events = []
    for user_id in result.order:
        player = result.players[user_id]
        if not player.alive:
            continue
        if any(catalog[cid].rule_key == "cleric" for cid in player.role_ids):
            player.level = min(10, player.level + 1)
            events.append(
                Event("group", "player.level_gained", {"user_id": user_id, "amount": 1})
            )
            if player.level == 10:
                result.phase = "game.finished"
                events.append(Event("group", "game.won", {"user_id": user_id}))
        elif any(catalog[cid].rule_key == "cleric" for cid in player.hand):
            events.append(
                Event(
                    f"user:{user_id}",
                    "divine_intervention.cleric_in_hand",
                    {"user_id": user_id},
                )
            )
    return result, events


def mandatory_play(chain, user_id, card_id, face_up, args):
    _mandatory_args(args)
    from .effects import apply_effects

    chain.state, events = apply_effects(
        chain.state,
        user_id,
        chain.catalog[card_id].effects,
        chain.catalog,
        choices={"played_card_id": card_id, "actor_id": user_id},
        rng=chain.rng,
    )
    chain.events.extend(events)
    chain.held.append((user_id, card_id))


def hoard(chain, user_id, card_id, face_up, args):
    _hoard_args(args)
    if face_up and chain.state.combat and chain.state.combat.reward_state:
        session = chain.state.combat.reward_state
        session["batches"][0]["remaining"] += 3
        session["held"].append(card_id)
        chain.state.players[user_id].hand.remove(card_id)
        chain.state.resolving_card_ids.append(card_id)
        return
    # The source stays owned, outside the recyclable discard, through the chain.
    chain.held.append((user_id, card_id))
    chain.take(user_id, "treasure", 3, face_up)
