"""Implemented Task 5 capabilities, bootstrapped without schema dependencies."""

from . import character
from .model import Event, RuleError


def exact_variant(variants):
    def validate(value):
        def same(a, b):
            if type(a) is not type(b):
                return False
            if isinstance(a, dict):
                return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
            if isinstance(a, list):
                return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
            return a == b

        if not any(same(value, expected) for expected in variants):
            raise ValueError("arguments do not match implemented source rule")

    return validate


def persist(state, target, args, catalog, *, choices, rng):
    source = choices["played_card_id"]
    actor = choices["actor_id"]
    if target != actor:
        raise RuleError("enabler requires self")
    p = state.players[target]
    key = catalog[source].rule_key
    if character.has_rule(p, catalog, key):
        raise RuleError("duplicate enabler")
    p.hand.remove(source)
    p.in_play.append(source)
    return state, []


def cheat(state, target, args, catalog, *, choices, rng):
    from .items import is_item_card

    p = state.players[target]
    source = choices["played_card_id"]
    cid = choices["card_id"]
    if (
        choices["actor_id"] != target
        or cid not in p.hand + p.in_play
        or not is_item_card(catalog[cid])
    ):
        raise RuleError("Cheat requires own carried Item")
    if cid in p.attachments.values():
        raise RuleError("item already has Cheat")
    if cid in p.hand:
        p.hand.remove(cid)
        p.in_play.append(cid)
    p.hand.remove(source)
    p.in_play.append(source)
    p.attachments[source] = cid
    from .items import reconcile_possessions

    reconcile_possessions(state, target, catalog)
    return state, []


def change_sex(state, target, args, catalog, *, choices, rng):
    p = state.players[target]
    p.character_sex = "male" if p.character_sex == "female" else "female"
    # Repeated changes do not multiply the printed next-combat penalty.
    if state.combat and target in state.combat.fighter_ids:
        state.combat.character_penalties[target] = args["next_combat_penalty"]
        p.next_combat_penalty = 0
    else:
        p.next_combat_penalty = args["next_combat_penalty"]
    from .items import reconcile_possessions

    reconcile_possessions(state, target, catalog)
    return state, [
        Event(
            "group",
            "character.sex_changed",
            {"user_id": target, "character_sex": p.character_sex},
        )
    ]


def discard_hireling(state, target, args, catalog, *, choices, rng):
    ids = [
        cid
        for cid in state.players[target].in_play
        if catalog[cid].rule_key == "hireling"
    ]
    character.discard_cards(state, target, ids, catalog)
    return state, []


def condition(key):
    def check(state, actor, target, catalog, args):
        p = state.players[actor]
        if key == "own_turn_identity_play":
            return actor == state.active_user_id or (
                state.phase == "turn.prepare" and state.turn_number <= 1
            )
        if key == "requires_identity":
            return bool(p.role_ids if args["kind"] == "role" else p.race_ids)
        if key == "monster_bonus":
            return character.matches_identity(p, catalog, args, disadvantage=True)
        if key == "item_identity_bonus":
            return character.matches_identity(p, catalog, args)
        if key == "warrior_wins_ties":
            return "warrior" in character.identities(p, catalog, "role")
        if key in {"elf_escape_bonus", "elf_helper_level"}:
            return "elf" in character.identities(p, catalog, "race")
        if key == "dwarf_carrying":
            return "dwarf" in character.identities(p, catalog, "race")
        if key == "halfling_double_sale":
            return "halfling" in character.identities(p, catalog, "race")
        if key in {"hireling_carry_item", "hireling_in_play"}:
            return (
                character.has_rule(state.players[target], catalog, "hireling")
                if key == "hireling_in_play"
                else not character.has_rule(p, catalog, "hireling")
            )
        if key == "rat_escape_eligibility":
            return bool(
                state.combat
                and any(
                    catalog[cid].bonus <= args["maximum_monster_level"]
                    for cid in state.combat.monster_ids
                )
            )
        if key in {"item_escape_bonus", "tuba_escape"}:
            return any(
                any(d["rule_key"] == key for d in catalog[cid].conditions)
                for cid in p.equipped
            )
        raise RuleError("unimplemented character condition")

    return check


CONDITIONS = {
    "own_turn_identity_play": [{}],
    "requires_identity": [{"kind": "race"}, {"kind": "role"}],
    "warrior_wins_ties": [{}],
    "elf_helper_level": [{"amount": 1, "can_win": True}],
    "elf_escape_bonus": [{"amount": 1}],
    "dwarf_carrying": [{"big_limit": None, "hand_limit": 6}],
    "halfling_double_sale": [{"max_items": 1, "multiplier": 2}],
    "hireling_carry_item": [
        {"ignore_requirements": True, "assign_outside_combat": True}
    ],
    "hireling_in_play": [{}],
    "item_escape_bonus": [{"amount": 2}],
    "item_identity_bonus": [{"race_any": ["elf"], "amount": 2}],
    "rat_escape_eligibility": [{"maximum_monster_level": 8, "usable_unequipped": True}],
    "tuba_escape": [{"amount": 3, "treasures_on_success": 1}],
    "monster_bonus": [
        {"amount": amount, identity: [race]}
        for amount, identity, race in [
            (3, "role_any", "cleric"),
            (4, "race_any", "elf"),
            (4, "role_any", "cleric"),
            (4, "role_any", "warrior"),
            (5, "race_any", "dwarf"),
            (5, "race_any", "elf"),
            (5, "role_any", "wizard"),
            (6, "race_any", "dwarf"),
            (6, "race_any", "elf"),
            (6, "role_any", "warrior"),
            (6, "role_any", "wizard"),
        ]
    ],
}
# The original multi-race Orc bonus is a single predicate, not two additive bonuses.
CONDITIONS["monster_bonus"].append({"amount": 3, "race_any": ["dwarf", "halfling"]})

SPECIALS = {
    "half_breed": (
        persist,
        {
            "max_races": 2,
            "single_race_no_disadvantages": True,
            "discard_when_no_race": True,
        },
    ),
    "super_munchkin": (
        persist,
        {
            "max_classes": 2,
            "single_class_no_disadvantages": True,
            "discard_when_no_class": True,
        },
    ),
    "hireling": (persist, {"carried_items": 1}),
    "ignore_one_item_restrictions": (cheat, {"discard_when_item_lost": True}),
    "change_sex": (change_sex, {"permanent": True, "next_combat_penalty": -5}),
    "discard_hireling": (discard_hireling, {}),
}

ABILITIES = {
    "warrior_berserk": (character.berserk, "either", 1, "combat", 3, ["combat.active"]),
    "cleric_turn_undead": (
        character.turn_undead,
        "either",
        1,
        "combat",
        3,
        ["combat.active"],
    ),
    "thief_backstab": (character.backstab, "either", 1, "combat", 1, ["combat.active"]),
    "thief_theft": (
        character.theft,
        "either",
        1,
        "unlimited",
        None,
        [
            "turn.prepare",
            "turn.after_door",
            "turn.charity",
            "combat.active",
            "combat.run_away",
        ],
    ),
    "wizard_charm": (character.charm, "hand", 3, "unlimited", None, ["combat.active"]),
    "wizard_flight": (
        character.flight,
        "either",
        1,
        "escape_attempt",
        3,
        ["combat.run_away"],
    ),
    "halfling_escape_retry": (
        character.retry_escape,
        "either",
        1,
        "escape_attempt",
        1,
        ["combat.run_away"],
    ),
    "hireling_escape": (
        character.automatic_escape,
        "in_play",
        1,
        "escape_attempt",
        1,
        ["combat.run_away"],
    ),
    "rat_on_a_stick_escape": (
        character.automatic_escape,
        "in_play",
        1,
        "escape_attempt",
        1,
        ["combat.run_away"],
    ),
    "cleric_resurrection": (
        character.resurrection_handler,
        "hand",
        1,
        "unlimited",
        None,
        [
            "turn.prepare",
            "turn.after_door",
            "turn.charity",
            "combat.active",
            "combat.run_away",
        ],
    ),
}


def register(registered, specials, conditions, abilities):
    specials.update(
        {
            key: registered(handler, exact_variant([args]))
            for key, (handler, args) in SPECIALS.items()
        }
    )
    conditions.update(
        {
            key: registered(condition(key), exact_variant(args))
            for key, args in CONDITIONS.items()
        }
    )
    for key, (handler, zone, count, scope, maximum, phases) in ABILITIES.items():
        cost = {"zone": zone, "count": count}
        if key == "wizard_charm":
            cost["mode"] = "all_hand"
        args = {
            "cost": cost,
            "limit": {"scope": scope, "max_uses": maximum},
            "phases": phases,
        }
        variants = [args]
        if key != "wizard_charm":
            variants.append({**args, "cost": {**cost, "mode": "exact"}})
        abilities[key] = registered(handler, exact_variant(variants))
