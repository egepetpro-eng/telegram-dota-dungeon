"""Closed monster conditions and voluntary printed monster actions."""

from copy import deepcopy
from .model import RuleError, Event
from .character import identities, matches_identity, discard_cards
from .items import is_item_card, can_use


def has_condition(card, key):
    return next((x["args"] for x in card.conditions if x["rule_key"] == key), None)


def condition(key):
    def check(state, actor, target, catalog, args):
        from .combat import monster_card, leader_id, combat_strength

        p = state.players[actor]
        c = state.combat
        if key == "participant_only":
            return bool(c and actor in c.fighter_ids)
        if key == "item_changes_losing_to_winning":
            return bool(
                c and actor in c.fighter_ids
            )  # Final post-acquisition comparison is performed by take_item_to_win.
        if key == "after_combat":
            return state.after_combat and actor == state.active_user_id
        if key == "not_highest_level":
            return state.players[target].level < max(
                x.level for x in state.players.values()
            )
        if key == "amazon_female":
            return p.character_sex == "female"
        if key == "will_not_pursue":
            return p.level <= args["maximum_level"] and not matches_identity(
                p,
                catalog,
                {"race_any": args.get("except_races", [])},
                disadvantage=True,
            )
        if key == "may_ignore_monster":
            return not matches_identity(
                p, catalog, {"race_any": args["except_races"]}, disadvantage=True
            )
        if key == "cleric_chase_away":
            return "cleric" in identities(p, catalog, "role")
        if key == "no_attack_and_exchange":
            return matches_identity(p, catalog, args)
        if key == "sandals_door_curse_immunity":
            return any(
                catalog[cid].rule_key == "sandals_of_protection"
                and can_use(p, cid, catalog)
                for cid in p.equipped
            )
        if key == "kneepads_forced_help":
            return (
                state.players[target].level > p.level
                and p.level < 9
                and (not c or c.helper_id is None)
            )
        if key == "bribe_monster":
            return any(
                is_item_card(catalog[cid])
                and catalog[cid].value >= args["minimum_item_value"]
                for cid in p.hand + p.in_play
            )
        if key == "discard_weapon_pole_or_staff_to_escape":
            return any(catalog[cid].rule_key in WEAPONS for cid in p.in_play)
        if key == "elf_extra_treasure":
            return bool(
                c
                and any(
                    "elf" in identities(state.players[uid], catalog, "race")
                    for uid in c.fighter_ids
                )
            )
        if key == "extra_level_if_fire_flame":
            if not c:
                return False
            equipment = [
                cid
                for uid in c.fighter_ids
                for cid in state.players[uid].equipped
                if can_use(state.players[uid], cid, catalog)
            ]
            shots = [
                cid for cid in c.played_card_ids if c.card_sides.get(cid) == "fighters"
            ]
            return any("fire_flame" in catalog[cid].tags for cid in equipment + shots)
        if key == "extra_level_if_solo_without_bonuses":
            return bool(
                c
                and len(c.fighter_ids) == 1
                and combat_strength(state, actor, catalog) == p.level
            )
        if key in {
            "cannot_run_away",
            "no_helper",
            "level_only_combat",
            "bonuses_only_combat",
            "automatic_escape",
            "escape_bonus",
            "run_away_loses_levels",
            "discard_item_before_combat",
        }:
            return bool(
                c
                and any(
                    has_condition(monster_card(state, mid, catalog), key) is not None
                    for mid in c.monster_ids
                )
            )
        raise RuleError("unimplemented monster condition")

    return check


WEAPONS = {
    "eleven_foot_pole",
    "staff_of_napalm",
    "wand_of_dowsing",
    "swiss_army_polearm",
}


def monster_action_options(state, actor, catalog):
    from .combat import monster_card

    c = state.combat
    if not c or actor not in c.fighter_ids or state.pending_decision:
        return []
    p = state.players[actor]
    result = []
    for mid in c.monster_ids:
        card = monster_card(state, mid, catalog)
        for key, option in [
            ("bribe_monster", "bribe"),
            ("may_ignore_monster", "ignore"),
            ("cleric_chase_away", "chase_away"),
            ("no_attack_and_exchange", "exchange"),
            ("amazon_female", "peaceful"),
            ("discard_weapon_pole_or_staff_to_escape", "distract"),
        ]:
            args = has_condition(card, key)
            if args is None or not condition(key)(state, actor, actor, catalog, args):
                continue
            if option == "distract":
                if (
                    state.phase != "combat.run_away"
                    or (actor, mid) not in c.escape_pending
                    or (actor, mid) in c.escape_rolls
                ):
                    continue
                cards = [cid for cid in p.in_play if catalog[cid].rule_key in WEAPONS]
            elif state.phase != "combat.active":
                continue
            elif option == "bribe":
                cards = [
                    cid for cid in p.hand + p.in_play if is_item_card(catalog[cid])
                ]
            elif option == "exchange":
                cards = [
                    cid for cid in p.hand + p.in_play if catalog[cid].deck == "treasure"
                ]
            else:
                cards = []
            result.append(
                dict(
                    monster_id=mid,
                    option=option,
                    card_ids=cards,
                    count=(
                        2
                        if option == "exchange"
                        else 1 if option == "distract" else None
                    ),
                    minimum_value=200 if option == "bribe" else None,
                )
            )
    return result


def monster_action(state, actor, monster_id, choices, catalog, rng, now):
    from .combat import remove_foe, monster_rewards, offer_automatic_escape

    if not isinstance(choices, dict) or set(choices) - {"option", "card_ids"}:
        raise RuleError("invalid monster choices")
    option = choices.get("option")
    spec = next(
        (
            x
            for x in monster_action_options(state, actor, catalog)
            if x["monster_id"] == monster_id and x["option"] == option
        ),
        None,
    )
    if spec is None:
        raise RuleError("monster action unavailable")
    cards = choices.get("card_ids", [])
    if (
        not isinstance(cards, list)
        or any(not isinstance(c, str) for c in cards)
        or len(cards) != len(set(cards))
        or not set(cards) <= set(spec["card_ids"])
    ):
        raise RuleError("invalid monster cost")
    if spec["count"] is not None and len(cards) != spec["count"]:
        raise RuleError("wrong monster cost count")
    if (
        spec["minimum_value"] is not None
        and sum(catalog[c].value for c in cards) < spec["minimum_value"]
    ):
        raise RuleError("insufficient bribe")
    result = deepcopy(state)
    discard_cards(result, actor, cards, catalog)
    if option == "distract":
        return offer_automatic_escape(result, actor, monster_id, catalog, rng, now)
    if option == "exchange":
        from .draw import draw_cards

        result, events = draw_cards(result, actor, "treasure", 2, False, catalog, rng)
    else:
        events = []
    treasures = (
        1
        if option == "peaceful"
        else (
            monster_rewards(result, monster_id, catalog)[1]
            if option == "chase_away"
            else 0
        )
    )
    result, ev = remove_foe(
        result,
        monster_id,
        catalog,
        rng,
        outcome="avoidance",
        treasures=treasures,
        now=now,
    )
    return result, events + ev


def force_help(state, actor, helper, catalog, now):
    from .combat import leader_id, ask_help, accept_help, monster_rewards

    if (
        not state.combat
        or actor != leader_id(state)
        or helper not in state.players
        or not state.players[helper].alive
    ):
        raise RuleError("invalid forced helper")
    p = state.players[actor]
    if not any(
        catalog[c].rule_key == "kneepads_of_allure" and can_use(p, c, catalog)
        for c in p.equipped
    ):
        raise RuleError("Kneepads must be in use")
    if (
        state.players[helper].level <= p.level
        or p.level
        + sum(monster_rewards(state, m, catalog)[0] for m in state.combat.monster_ids)
        >= 10
    ):
        raise RuleError("cannot force this helper or winning level")
    result, events = ask_help(state, actor, helper, 0, [], catalog)
    result, ev = accept_help(result, helper, catalog, now=now)
    if result.combat:
        result.combat.forced_helper = True
    return result, events + ev


def register(registered, conditions):
    from .character_rules import exact_variant

    conditions.update(
        {k: registered(condition(k), exact_variant(v)) for k, v in SPECS.items()}
    )


SPECS = {
    "after_combat": [{}],
    "amazon_female": [{"levels": 0, "sex": "female", "treasures": 1}],
    "automatic_escape": [{}],
    "bonuses_only_combat": [{}],
    "bribe_monster": [{"minimum_item_value": 200, "rewards": False}],
    "cannot_run_away": [{}],
    "cleric_chase_away": [{"levels": 0, "treasures": True}],
    "discard_item_before_combat": [{"amount": 1}],
    "discard_weapon_pole_or_staff_to_escape": [{"amount": 1}],
    "elf_extra_treasure": [{"amount": 1}],
    "escape_bonus": [{"amount": -1}, {"amount": 1}, {"amount": -2}],
    "extra_level_if_fire_flame": [{"amount": 1}],
    "extra_level_if_solo_without_bonuses": [{"amount": 1}],
    "item_changes_losing_to_winning": [{}],
    "kneepads_forced_help": [
        {"cannot_force_win": True, "minimum_helper": "strictly_higher_level"}
    ],
    "level_only_combat": [{}],
    "may_ignore_monster": [{"except_races": ["halfling"], "rewards": False}],
    "no_attack_and_exchange": [
        {
            "discard_treasures": 2,
            "draw_treasures": 2,
            "role_any": ["thief"],
            "visibility": "private",
        }
    ],
    "no_helper": [{}],
    "not_highest_level": [{"ties_for_highest_disallowed": True}],
    "participant_only": [{}],
    "run_away_loses_levels": [{"amount": 2}, {"amount": 1}],
    "sandals_door_curse_immunity": [{}],
    "will_not_pursue": [
        {"maximum_level": 4},
        {"maximum_level": 3},
        {"maximum_level": 5},
        {"except_races": ["elf"], "maximum_level": 4},
    ],
}
