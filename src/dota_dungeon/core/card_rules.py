"""Implemented rule capabilities, registered by code rather than card data.

Special, condition and trigger validators receive their descriptor's ``args``.
Ability validators receive its complete cost/limit/phases descriptor (without
``key``), so the implemented ability can constrain its usage policy.
"""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RegisteredRule:
    handler: Callable[..., Any]
    validate_args: Callable[[dict[str, Any]], None]


SPECIAL_HANDLERS: dict[str, RegisteredRule] = {}
CONDITION_HANDLERS: dict[str, RegisteredRule] = {}
TRIGGER_HANDLERS: dict[str, RegisteredRule] = {}
ABILITY_HANDLERS: dict[str, RegisteredRule] = {}
SPECIAL_RULES = SPECIAL_HANDLERS

# Import code-owned builtins so release validation sees real implementations.
from .draw_triggers import (  # noqa: E402
    all_clerics_gain_level,
    hoard,
    mandatory_play,
    _cleric_args,
    _hoard_args,
    _mandatory_args,
)

TRIGGER_HANDLERS.update(
    {
        "mandatory_play": RegisteredRule(mandatory_play, _mandatory_args),
        "hoard": RegisteredRule(hoard, _hoard_args),
    }
)
SPECIAL_HANDLERS["all_clerics_gain_level"] = RegisteredRule(
    all_clerics_gain_level, _cleric_args
)

from .character_rules import register as _register_character

_register_character(
    RegisteredRule, SPECIAL_HANDLERS, CONDITION_HANDLERS, ABILITY_HANDLERS
)

from .combat_rules import register as _register_combat

_register_combat(RegisteredRule, SPECIAL_HANDLERS)

from .decisions import decision_options

from .loss_rules import register as _register_losses

_register_losses(RegisteredRule, SPECIAL_HANDLERS)

from .response_rules import register as _register_responses

_register_responses(RegisteredRule, SPECIAL_HANDLERS)

from .monster_rules import register as _register_monsters

_register_monsters(RegisteredRule, CONDITION_HANDLERS)


def reactive_card_options(state, actor_id, card_id, catalog, *, now=None):
    """Return legal response operands without revealing another player's hand."""
    from copy import deepcopy
    from itertools import combinations
    from random import Random
    from .decisions import time_value
    from .play import play_card
    from .model import RuleError

    card = catalog.get(card_id)
    p = state.players.get(actor_id)
    if card is None or p is None or card_id not in p.hand + p.in_play:
        return []
    key = card.rule_key
    d = state.pending_decision
    c = state.combat
    candidates = []
    if key == "wishing_ring":
        if d and d.kind == "curse_response":
            candidates.append(
                ({"player_id": d.payload["target_id"]}, {"effect_id": d.id})
            )
        if not d:
            candidates.extend(
                ({"player_id": uid}, {"curse_id": cid})
                for uid, owner in state.players.items()
                for cid in owner.in_play
                if catalog[cid].kind == "curse"
            )
    elif key == "loaded_die":
        ids = (
            [d.id]
            if d and d.kind == "die_response" and d.payload["owner"] == actor_id
            else []
        )
        if c:
            ids.extend(
                rid
                for pair, rid in c.escape_roll_ids.items()
                if pair[0] == actor_id
                and pair in c.escape_rolls
                and pair not in c.automatic_escapes
            )
        candidates.extend(
            ({}, dict(roll_id=rid, result=value))
            for rid in ids
            for value in range(1, 7)
        )
    elif key in {"invisibility_potion", "flask_of_glue"} and c:
        candidates.extend(
            (
                {"player_id": pair[0]} if key == "flask_of_glue" else {},
                {"attempt_id": rid},
            )
            for pair, rid in c.escape_roll_ids.items()
            if pair in c.escape_rolls
            and (key == "flask_of_glue" or pair[0] == actor_id)
        )
    elif key == "instant_wall" and c:
        candidates.extend(
            ({}, {"player_ids": list(ids)})
            for count in (1, 2)
            for ids in combinations(c.fighter_ids, count)
        )
    result = []
    for target, choices in candidates:
        try:
            play_card(
                deepcopy(state),
                actor_id,
                card_id,
                target,
                catalog,
                Random(0),
                time_value(now),
                choices=choices,
            )
        except (RuleError, ValueError):
            continue
        result.append(dict(target=target, choices=choices))
    return result


def resolve_special_rule(state, actor_id, rule_key, target, choices, catalog, rng, now):
    """Trusted dispatcher for a descriptor on the actor's selected physical card."""
    from .play import play_card
    from .model import RuleError

    if not isinstance(choices, dict) or "card_id" not in choices:
        raise RuleError("special dispatch requires source card_id")
    cid = choices["card_id"]
    if cid not in catalog or not any(
        e.get("rule_key") == rule_key for e in catalog[cid].effects
    ):
        raise RuleError("rule does not belong to source")
    return play_card(
        state,
        actor_id,
        cid,
        target,
        catalog,
        rng,
        now,
        choices={k: v for k, v in choices.items() if k != "card_id"},
    )
