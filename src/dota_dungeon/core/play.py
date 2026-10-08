"""Atomic player initiated card play and server-defined discard costs."""

from copy import deepcopy
from datetime import datetime
from random import Random

from . import card_rules, items
from .effects import apply_effects
from .model import Catalog, Event, GameState, Player, RuleError


def validate_cost(player: Player, cost: dict, cost_ids: list[str]) -> None:
    """Validate selections; callers apply the cost on their transition copy."""
    if not isinstance(cost, dict) or set(cost) - {"zone", "count", "mode"}:
        raise RuleError("invalid cost")
    zone, count, mode = cost.get("zone"), cost.get("count"), cost.get("mode", "exact")
    if zone not in {"hand", "in_play", "either"} or type(count) is not int or count < 0:
        raise RuleError("invalid cost")
    if mode not in {"exact", "all_hand"} or (mode == "all_hand" and zone != "hand"):
        raise RuleError("invalid cost mode")
    if not isinstance(cost_ids, list) or any(not isinstance(cid, str) for cid in cost_ids):
        raise RuleError("invalid cost selection")
    if len(cost_ids) != len(set(cost_ids)):
        raise RuleError("duplicate cost card")
    eligible = player.hand if zone == "hand" else player.in_play if zone == "in_play" else player.hand + player.in_play
    if not set(cost_ids).issubset(eligible):
        raise RuleError("cost card is not owned in required zone")
    if mode == "all_hand":
        if len(player.hand) < count or set(cost_ids) != set(player.hand):
            raise RuleError("cost requires entire hand and minimum hand size")
    elif len(cost_ids) != count:
        raise RuleError("insufficient or excessive discard cost")


def _target(
    state: GameState,
    actor_id: int,
    rule: str,
    target: dict,
    catalog: Catalog,
    *,
    played_card_id: str | None = None,
) -> int:
    if not isinstance(target, dict):
        raise RuleError("target must be an object")
    allowed = {
        "none": set(),
        "self": {"player_id"},
        "player": {"player_id"},
        "monster": {"monster_id"},
        "open_item": {"player_id", "card_id"},
        "identity": {"player_id", "card_id"},
        "discard": {"card_id"},
        "combat": {"player_id", "monster_id"},
    }
    if rule not in allowed or set(target) - allowed[rule]:
        raise RuleError("invalid target operands")
    player_id = target.get("player_id", actor_id)
    if type(player_id) is not int or player_id not in state.players:
        raise RuleError("unknown target player")
    if rule == "self" and player_id != actor_id:
        raise RuleError("card requires self target")
    if rule == "player" and "player_id" not in target:
        raise RuleError("player target required")
    if rule in {"monster", "combat"}:
        if not state.combat:
            raise RuleError("no active combat")
        if rule == "monster" or "monster_id" in target:
            if target.get("monster_id") not in state.combat.monster_ids:
                raise RuleError("unknown target monster")
        if "player_id" in target and player_id not in state.combat.fighter_ids:
            raise RuleError("target is not a fighter")
    if rule in {"open_item", "identity"}:
        cid = target.get("card_id")
        own_cheat_item = (
            rule == "open_item"
            and played_card_id in catalog
            and catalog[played_card_id].rule_key == "cheat"
            and player_id == actor_id
            and cid in state.players[player_id].hand
        )
        if (
            cid not in state.players[player_id].in_play and not own_cheat_item
        ) or cid not in catalog:
            raise RuleError("target is not an open owned card")
        kinds = {"item"} if rule == "open_item" else {"role", "race"}
        if (rule == "open_item" and not items.is_item_card(catalog[cid])) or (
            rule != "open_item" and catalog[cid].kind not in kinds
        ):
            raise RuleError("invalid target card kind")
    if (
        rule == "discard"
        and target.get("card_id") not in state.door_discard + state.treasure_discard
    ):
        raise RuleError("target is not discarded")
    return player_id


def play_card(
    state: GameState,
    actor_id: int,
    card_id: str,
    target: dict,
    catalog: Catalog,
    rng: Random,
    now: datetime,
) -> tuple[GameState, list[Event]]:
    if actor_id not in state.players or not state.players[actor_id].alive:
        raise RuleError("unknown or dead player")
    if card_id not in catalog:
        raise RuleError("unknown card")
    from .combat import validate_escape_action

    validate_escape_action(
        state,
        actor_id,
        "play_card",
        target,
        catalog,
        rule_key=catalog[card_id].rule_key,
    )
    card, owner = catalog[card_id], state.players[actor_id]
    if state.phase not in card.play_phases or state.phase in {"lobby", "game.finished"}:
        raise RuleError("card cannot be played in this phase")
    carried_shot = card.kind == "one_shot" and card_id in owner.in_play
    if card_id not in owner.hand and not carried_shot:
        raise RuleError("card is not owned in playable zone")
    target_id = _target(
        state, actor_id, card.target_rule, target, catalog, played_card_id=card_id
    )
    if card.kind in {"role", "race", "item"}:
        if target_id != actor_id:
            raise RuleError("possessions require self target")
        if card.kind in {"role", "race"}:
            return items.play_identity(state, actor_id, card_id, catalog)
        return items.carry(state, actor_id, card_id, catalog)
    if card.kind not in {"level_up", "one_shot", "curse", "modifier", "special"}:
        raise RuleError("card cannot be played directly")
    if card.kind == "modifier" and (
        not state.combat or target.get("monster_id") not in state.combat.monster_ids
    ):
        raise RuleError("modifier requires a monster target")
    for condition in card.conditions:
        registered = card_rules.CONDITION_HANDLERS.get(condition["rule_key"])
        if registered is None:
            raise RuleError("unimplemented condition")
        registered.validate_args(deepcopy(condition["args"]))
        if not registered.handler(
            deepcopy(state), actor_id, target_id, catalog, deepcopy(condition["args"])
        ):
            raise RuleError("card condition not met")
    result = deepcopy(state)
    transition_rng = deepcopy(rng)
    was_reacting = bool(result.combat and result.combat.reaction_deadline)
    choices = {**target, "played_card_id": card_id, "actor_id": actor_id}
    if card.rule_key == "really_impressive_title":
        result.players[actor_id].hand.remove(card_id)
        result.players[actor_id].in_play.append(card_id)
        events = []
    else:
        result, events = apply_effects(
            result,
            target_id,
            card.effects,
            catalog,
            choices=choices,
            rng=transition_rng,
        )
    owner = result.players[actor_id]
    persistent = card_id in result.players[target_id].in_play and not carried_shot
    if not persistent:
        items.remove_owned_card(owner, card_id)
        if result.combat:
            result.combat.played_card_ids.append(card_id)
            if card.kind == "modifier":
                result.combat.modifier_ids.append(card_id)
        else:
            (
                result.door_discard if card.deck == "door" else result.treasure_discard
            ).append(card_id)
    if carried_shot and not persistent:
        items.reconcile_possessions(result, actor_id, catalog)
    if result.combat:
        from .combat import restart_reaction

        events.extend(restart_reaction(result, catalog, now, was_reacting))
    events.append(
        Event(
            "group",
            "card.played",
            {"actor_id": actor_id, "card_id": card_id, "target": target.copy()},
        )
    )
    rng.setstate(transition_rng.getstate())
    return result, events
