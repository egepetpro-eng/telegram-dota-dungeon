"""Source identity rules; imports stay independent of the schema/registry bootstrap."""

from copy import deepcopy
from datetime import datetime
from random import Random
from .model import Catalog, Event, GameState, RuleError

ALIASES = {
    "warrior.berserk": "warrior_berserk",
    "thief.backstab": "thief_backstab",
    "thief.steal": "thief_theft",
    "wizard.flight": "wizard_flight",
    "wizard.charm": "wizard_charm",
    "cleric.resurrect": "cleric_resurrection",
    "cleric.turn_undead": "cleric_turn_undead",
    "halfling.retry_escape": "halfling_escape_retry",
}


def identities(player, catalog, kind):
    values = {
        catalog[cid].rule_key
        for cid in (player.role_ids if kind == "role" else player.race_ids)
    }
    if kind == "race" and not player.race_ids:
        values.add("human")
    return values


def has_rule(player, catalog, key):
    return any(catalog[cid].rule_key == key for cid in player.in_play)


def no_disadvantages(player, catalog, kind):
    return len(
        player.role_ids if kind == "role" else player.race_ids
    ) == 1 and has_rule(
        player, catalog, "super_munchkin" if kind == "role" else "half_breed"
    )


def matches_identity(player, catalog, args, *, disadvantage=False):
    for kind, key in [("role", "role_any"), ("race", "race_any")]:
        if key in args and identities(player, catalog, kind).intersection(args[key]):
            if not disadvantage or not no_disadvantages(player, catalog, kind):
                return True
    return False


def effective_item_rules(state: GameState, user_id: int, catalog: Catalog) -> dict:
    p = state.players[user_id]
    return {
        "big_limit": None if "dwarf" in identities(p, catalog, "race") else 1,
        "max_classes": 2 if has_rule(p, catalog, "super_munchkin") else 1,
        "max_races": 2 if has_rule(p, catalog, "half_breed") else 1,
        "ignored_item_ids": set(p.attachments.values())
        | set(p.hireling_items.values()),
    }


def effective_hand_limit(state: GameState, user_id: int, catalog: Catalog) -> int:
    return 6 if "dwarf" in identities(state.players[user_id], catalog, "race") else 5


def start_character_combat(state, catalog):
    for uid in state.combat.fighter_ids:
        p = state.players[uid]
        if p.next_combat_penalty or uid not in state.combat.character_penalties:
            state.combat.character_penalties[uid] = p.next_combat_penalty
        p.next_combat_penalty = 0


def discard_cards(state, user_id, card_ids, catalog):
    from .items import remove_owned_card, reconcile_possessions
    from .trade import cancel_trades_for_cards

    for cid in card_ids:
        remove_owned_card(state.players[user_id], cid)
        getattr(state, f"{catalog[cid].deck}_discard").append(cid)
    reconcile_possessions(state, user_id, catalog)
    cancel_trades_for_cards(state, card_ids)


def _ability_descriptor(state, actor, key, catalog):
    p = state.players[actor]
    for cid in p.role_ids + p.race_ids + p.in_play:
        for descriptor in catalog[cid].abilities:
            if descriptor["key"] == key:
                return cid, descriptor
    raise RuleError("ability source is not in play")


def _validate_ability_target(state, actor, key, target, catalog, source):
    permitted = {
        "warrior_berserk": set(),
        "cleric_turn_undead": set(),
        "wizard_charm": {"monster_id"},
        "thief_backstab": {"player_id"},
        "thief_theft": {"player_id", "card_id"},
        "cleric_resurrection": {"deck"},
        "wizard_flight": {"monster_id"},
        "halfling_escape_retry": {"monster_id"},
        "hireling_escape": {"monster_id"},
        "rat_on_a_stick_escape": {"monster_id"},
    }
    if not isinstance(target, dict) or set(target) != permitted[key]:
        raise RuleError("invalid ability target operands")
    participant = bool(state.combat and actor in state.combat.fighter_ids)
    if (
        key in {"warrior_berserk", "cleric_turn_undead", "wizard_charm"}
        and not participant
    ):
        raise RuleError("ability requires combat participant")
    if key == "cleric_turn_undead" and not any(
        "undead"
        in __import__("dota_dungeon.core.combat", fromlist=["monster_card"])
        .monster_card(state, cid, catalog)
        .tags
        for cid in state.combat.monster_ids
    ):
        raise RuleError("no Undead monster")
    if key == "wizard_charm" and target["monster_id"] not in state.combat.monster_ids:
        raise RuleError("unknown monster")
    if key == "thief_backstab":
        victim = target["player_id"]
        if (
            type(victim) is not int
            or not state.combat
            or victim == actor
            or victim not in state.combat.fighter_ids
        ):
            raise RuleError("backstab requires another fighter")
    if key == "thief_theft":
        victim, cid = target["player_id"], target["card_id"]
        if type(victim) is not int or victim not in state.players or victim == actor:
            raise RuleError("invalid theft victim")
        from .items import is_item_card

        if (
            cid not in state.players[victim].in_play
            or not is_item_card(catalog[cid])
            or catalog[cid].size == "big"
        ):
            raise RuleError("theft requires small carried Item")
        if state.combat and (
            actor in state.combat.fighter_ids or victim in state.combat.fighter_ids
        ):
            raise RuleError("fighters cannot steal or be stolen from")
    if key in {
        "wizard_flight",
        "halfling_escape_retry",
        "hireling_escape",
        "rat_on_a_stick_escape",
    }:
        pair = (actor, target["monster_id"])
        if not state.combat or pair not in state.combat.escape_pending:
            raise RuleError("no own escape attempt")
        if (
            key in {"hireling_escape", "rat_on_a_stick_escape"}
            and pair in state.combat.escape_rolls
        ):
            raise RuleError("automatic escape must precede the roll")
        if key in {"wizard_flight", "halfling_escape_retry"}:
            if pair not in state.combat.escape_rolls:
                raise RuleError("ability requires stored die roll")
            if key == "halfling_escape_retry":
                from .combat import escape_modifier

                if (
                    state.combat.escape_rolls[pair]
                    + escape_modifier(state, actor, pair[1], catalog)
                    >= 5
                ):
                    raise RuleError("retry requires failed roll")
        from .combat import monster_card, escape_possible

        if key in {"hireling_escape", "rat_on_a_stick_escape"} and not escape_possible(
            state, pair[1], catalog
        ):
            raise RuleError("monster forbids escape")
        if (
            key == "rat_on_a_stick_escape"
            and monster_card(state, pair[1], catalog).bonus > 8
        ):
            raise RuleError("monster level exceeds Rat limit")
    if key == "cleric_resurrection" and target["deck"] not in {"door", "treasure"}:
        raise RuleError("invalid resurrection deck")


def use_ability(
    state: GameState,
    actor_id: int,
    ability_key: str,
    target: dict,
    cost_ids: list[str],
    catalog: Catalog,
    rng: Random,
    now: datetime,
):
    from .play import validate_cost
    from .card_rules import ABILITY_HANDLERS

    if actor_id not in state.players or not state.players[actor_id].alive:
        raise RuleError("unknown or dead player")
    key = ALIASES.get(ability_key, ability_key)
    from .combat import validate_escape_action

    validate_escape_action(
        state, actor_id, "use_ability", target, catalog, rule_key=key
    )
    if key not in ABILITY_HANDLERS:
        raise RuleError("unimplemented ability")
    source, descriptor = _ability_descriptor(state, actor_id, key, catalog)
    ABILITY_HANDLERS[key].validate_args(
        {k: v for k, v in descriptor.items() if k != "key"}
    )
    if state.phase not in descriptor["phases"]:
        raise RuleError("ability cannot be used in this phase")
    _validate_ability_target(state, actor_id, key, target, catalog, source)
    player = state.players[actor_id]
    validate_cost(player, descriptor["cost"], cost_ids)
    from .help_contracts import require_unpromised
    require_unpromised(state, actor_id, cost_ids)
    if any((actor_id, cid) in state.pending_initial_triggers for cid in cost_ids):
        raise RuleError("mandatory trigger card is reserved")
    for cid in cost_ids:
        if (
            cid in player.in_play
            and (catalog[cid].kind == "curse" or cid == source)
            and not (
                key in {"hireling_escape", "rat_on_a_stick_escape"} and cid == source
            )
        ):
            raise RuleError("cannot discard permanent curse or ability source")
    if key in {"hireling_escape", "rat_on_a_stick_escape"} and cost_ids != [source]:
        raise RuleError("ability must discard its printed source")
    if key == "cleric_resurrection":
        return resurrection_handler(
            state, actor_id, target, catalog, rng, now=now, cost_ids=cost_ids
        )
    scope = descriptor["limit"]["scope"]
    maximum = descriptor["limit"]["max_uses"]
    usage = (
        actor_id,
        key,
        target.get("player_id") if key == "thief_backstab" else None,
    )
    escape_usage = (actor_id, target.get("monster_id"), key)
    uses = (
        state.combat.ability_uses.get(usage, 0)
        if scope == "combat"
        else (
            state.combat.escape_uses.get(escape_usage, 0)
            if scope == "escape_attempt"
            else 0
        )
    )
    if maximum is not None and uses >= maximum:
        raise RuleError("ability usage limit")
    result = deepcopy(state)
    transition_rng = deepcopy(rng)
    reacting = bool(result.combat and result.combat.reaction_deadline)
    discard_cards(result, actor_id, cost_ids, catalog)
    if scope == "combat":
        result.combat.ability_uses[usage] = uses + 1
    elif scope == "escape_attempt":
        result.combat.escape_uses[escape_usage] = uses + 1
    result, events = ABILITY_HANDLERS[key].handler(
        result,
        actor_id,
        target,
        catalog,
        transition_rng,
        **(
            {"now": now}
            if key
            in {
                "thief_theft",
                "hireling_escape",
                "rat_on_a_stick_escape",
                "wizard_charm",
            }
            else {}
        ),
    )
    if result.combat and result.phase == "combat.active":
        from .combat import restart_reaction

        events.extend(restart_reaction(result, catalog, now, reacting))
    events.append(
        Event(
            "group",
            "ability.used",
            {
                "user_id": actor_id,
                "ability_key": key,
                "cost_ids": cost_ids.copy(),
                "target": target.copy(),
            },
        )
    )
    rng.setstate(transition_rng.getstate())
    return result, events


def berserk(state, actor, target, catalog, rng):
    state.combat.temporary_strength[actor] = (
        state.combat.temporary_strength.get(actor, 0) + 1
    )
    return state, []


def turn_undead(state, actor, target, catalog, rng):
    state.combat.temporary_strength[actor] = (
        state.combat.temporary_strength.get(actor, 0) + 3
    )
    return state, []


def backstab(state, actor, target, catalog, rng):
    victim = target["player_id"]
    state.combat.temporary_strength[victim] = (
        state.combat.temporary_strength.get(victim, 0) - 2
    )
    return state, []


def theft(state, actor, target, catalog, rng, *, now=None):
    if any(c.rule_key == "loaded_die" for c in catalog.values()):
        from .loss_rules import die_opportunity

        return die_opportunity(
            state,
            actor,
            "thief_theft",
            catalog,
            rng,
            now,
            victim=target["player_id"],
            card_id=target["card_id"],
        )
    die = rng.randint(1, 6)
    cid = target["card_id"]
    victim = target["player_id"]
    if die >= 4:
        from .items import remove_owned_card, reconcile_possessions

        remove_owned_card(state.players[victim], cid)
        reconcile_possessions(state, victim, catalog)
        state.players[actor].in_play.append(cid)
        from .trade import cancel_trades_for_cards

        cancel_trades_for_cards(state, [cid])
    else:
        state.players[actor].level = max(1, state.players[actor].level - 1)
    return state, [
        Event(
            "group",
            "theft.rolled",
            {
                "user_id": actor,
                "victim_id": victim,
                "die": die,
                "success": die >= 4,
                "card_id": cid,
            },
        )
    ]


def flight(state, actor, target, catalog, rng):
    pair = (actor, target["monster_id"])
    state.combat.escape_bonuses[pair] = state.combat.escape_bonuses.get(pair, 0) + 1
    return state, []


def retry_escape(state, actor, target, catalog, rng):
    pair = (actor, target["monster_id"])
    die = rng.randint(1, 6)
    state.combat.escape_rolls[pair] = die
    return state, [
        Event(
            "group",
            "escape.rerolled",
            {"user_id": actor, "monster_id": pair[1], "die": die},
        )
    ]


def automatic_escape(state, actor, target, catalog, rng, *, now=None):
    from .combat import offer_automatic_escape

    return offer_automatic_escape(state, actor, target["monster_id"], catalog, rng, now)


def charm(state, actor, target, catalog, rng, *, now=None):
    from .combat import remove_foe, monster_rewards

    mid = target["monster_id"]
    treasures = monster_rewards(state, mid, catalog)[1]
    return remove_foe(
        state, mid, catalog, rng, outcome="charm", treasures=treasures, now=now
    )


def resurrection_handler(
    state, actor, target, catalog, rng, *, now=None, cost_ids=None
):
    if cost_ids is None or now is None:
        raise RuleError("resurrection requires draw costs and trusted time")
    if target["deck"] == "door":
        from .turn import open_door

        return open_door(state, actor, catalog, rng, resurrection_ids=cost_ids)
    from .combat import close_reaction

    return close_reaction(state, catalog, now, rng, resurrection_ids={actor: cost_ids})
