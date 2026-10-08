"""Closed declarative schema for source-verified card mechanics."""

from copy import deepcopy
from typing import Any

from dota_dungeon.core import card_rules
from dota_dungeon.core.catalog import DECKS, EFFECTS, KINDS


PHASES = {"turn.prepare", "turn.after_door", "turn.charity", "combat.active", "combat.run_away"}
TARGETS = {"none", "self", "player", "monster", "open_item", "identity", "discard", "combat"}
SLOTS = {"head", "armor", "feet", "one_hand", "two_hands"}
MECHANIC_DEFAULTS = {
    "value": 0, "bonus": 0, "slots": None, "size": "small", "effects": [],
    "tags": [], "treasures": 0, "levels": 1, "bad_stuff": [], "play_phases": [],
    "target_rule": "none", "restrictions": {}, "conditions": [], "abilities": [], "trigger": None,
}
MECHANIC_KEYS = {"deck", "kind", *MECHANIC_DEFAULTS}
PRESENTATION_KEYS = {"display_name_ru", "description_ru", "dota_entity_id", "source_refs"}


def object_fields(value: Any, allowed: set[str], required: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{path}: keys must be strings")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    if missing:
        raise ValueError(f"{path}: missing keys {sorted(missing)}")
    return value


def text(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: expected nonempty string")


def integer(value: Any, path: str, minimum: int | None = None) -> None:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = f" >= {minimum}" if minimum is not None else ""
        raise ValueError(f"{path}: expected integer{suffix} (not bool)")


def enum(value: Any, allowed: set[str], path: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{path}: invalid value; expected one of {sorted(allowed)}")


def sequence(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected list")
    return value


def strings(value: Any, path: str, *, unique: bool = False,
            nonempty: bool = False, choices: set[str] | None = None) -> None:
    sequence(value, path)
    if nonempty and not value:
        raise ValueError(f"{path}: expected nonempty list")
    for item in value:
        text(item, path)
        if choices is not None:
            enum(item, choices, path)
    if unique and len(value) != len(set(value)):
        raise ValueError(f"{path}: duplicate values")


def implemented_rule(registry: dict, key: Any, args: Any, path: str) -> None:
    text(key, f"{path}.rule_key")
    if not isinstance(args, dict):
        raise ValueError(f"{path}.args: expected object")
    rule = registry.get(key)
    if (not isinstance(rule, card_rules.RegisteredRule)
            or not callable(rule.handler) or not callable(rule.validate_args)):
        raise ValueError(f"{path}: unknown or unimplemented rule {key!r}")
    try:
        rule.validate_args(deepcopy(args))
    except ValueError as error:
        raise ValueError(f"{path}: invalid handler args: {error}") from error


def validate_operation(effect: Any, path: str) -> None:
    if not isinstance(effect, dict):
        raise ValueError(f"{path}: expected operation object")
    op = effect.get("op")
    enum(op, EFFECTS | {"special"}, f"{path}.op")
    if op == "special":
        object_fields(effect, {"op", "rule_key", "args"}, {"op", "rule_key", "args"}, path)
        implemented_rule(card_rules.SPECIAL_HANDLERS, effect["rule_key"], effect["args"], path)
    elif op in {"gain_level", "lose_level", "draw", "add_strength", "monster_modifier", "escape_modifier"}:
        allowed = {"op", "amount"}
        if op == "gain_level":
            allowed.add("can_win")
        if op == "draw":
            allowed.add("deck")
        object_fields(effect, allowed, {"op"}, path)
        integer(effect.get("amount", 1), f"{path}.amount",
                1 if op in {"gain_level", "lose_level", "draw"} else None)
        if op == "gain_level" and type(effect.get("can_win", False)) is not bool:
            raise ValueError(f"{path}.can_win: expected boolean")
        if op == "draw":
            enum(effect.get("deck", "treasure"), DECKS, f"{path}.deck")
    else:
        operand = "card_id" if op in {"remove_item", "persistent"} else "monster_id"
        object_fields(effect, {"op", operand}, {"op", operand}, path)
        text(effect[operand], f"{path}.{operand}")


def validate_presentation(raw: Any, path: str) -> None:
    object_fields(raw, PRESENTATION_KEYS, PRESENTATION_KEYS, path)
    for key in PRESENTATION_KEYS - {"source_refs"}:
        text(raw[key], f"{path}.{key}")
    strings(raw["source_refs"], f"{path}.source_refs", nonempty=True)


def validate_mechanics(raw: Any, path: str) -> dict:
    object_fields(raw, MECHANIC_KEYS, {"deck", "kind"}, path)
    result = deepcopy(MECHANIC_DEFAULTS)
    result.update(deepcopy(raw))
    enum(result["deck"], DECKS, f"{path}.deck")
    enum(result["kind"], KINDS, f"{path}.kind")
    for key, minimum in (("value", 0), ("bonus", None), ("treasures", 0), ("levels", 1)):
        integer(result[key], f"{path}.{key}", minimum)
    if result["slots"] is not None:
        enum(result["slots"], SLOTS, f"{path}.slots")
    enum(result["size"], {"small", "big"}, f"{path}.size")
    strings(result["tags"], f"{path}.tags", unique=True)
    strings(result["play_phases"], f"{path}.play_phases", unique=True, choices=PHASES)
    enum(result["target_rule"], TARGETS, f"{path}.target_rule")
    restrictions = result["restrictions"]
    list_keys = {"role_any", "race_any", "cannot_use_roles", "cannot_use_races"}
    object_fields(restrictions, list_keys | {"sex", "requires_rule"}, set(), f"{path}.restrictions")
    for key, value in restrictions.items():
        if key in list_keys:
            strings(value, f"{path}.restrictions.{key}", unique=True)
        elif key == "sex":
            enum(value, {"male", "female"}, f"{path}.restrictions.sex")
        else:
            text(value, f"{path}.restrictions.requires_rule")
    for key in ("effects", "bad_stuff"):
        for index, effect in enumerate(sequence(result[key], f"{path}.{key}")):
            validate_operation(effect, f"{path}.{key}[{index}]")
    for index, condition in enumerate(sequence(result["conditions"], f"{path}.conditions")):
        current = f"{path}.conditions[{index}]"
        object_fields(condition, {"rule_key", "args"}, {"rule_key", "args"}, current)
        implemented_rule(card_rules.CONDITION_HANDLERS, condition["rule_key"], condition["args"], current)
    trigger = result["trigger"]
    if trigger is not None:
        current = f"{path}.trigger"
        keys = {"rule_key", "timing", "visibility", "args"}
        object_fields(trigger, keys, keys, current)
        enum(trigger["timing"], {"acquired", "initial_deal"}, f"{current}.timing")
        enum(trigger["visibility"], {"inherit", "group"}, f"{current}.visibility")
        implemented_rule(card_rules.TRIGGER_HANDLERS, trigger["rule_key"], trigger["args"], current)
    for index, ability in enumerate(sequence(result["abilities"], f"{path}.abilities")):
        current = f"{path}.abilities[{index}]"
        keys = {"key", "cost", "limit", "phases"}
        object_fields(ability, keys, keys, current)
        object_fields(ability["cost"], {"zone", "count"}, {"zone", "count"}, f"{current}.cost")
        enum(ability["cost"]["zone"], {"hand", "in_play", "either"}, f"{current}.cost.zone")
        integer(ability["cost"]["count"], f"{current}.cost.count", 0)
        object_fields(ability["limit"], {"scope", "max_uses"}, {"scope", "max_uses"}, f"{current}.limit")
        enum(ability["limit"]["scope"], {"combat", "escape_attempt", "turn", "unlimited"}, f"{current}.limit.scope")
        if ability["limit"]["max_uses"] is not None:
            integer(ability["limit"]["max_uses"], f"{current}.limit.max_uses", 1)
        strings(ability["phases"], f"{current}.phases", unique=True, choices=PHASES)
        implemented_rule(card_rules.ABILITY_HANDLERS, ability["key"],
                         {key: value for key, value in ability.items() if key != "key"}, current)
    return result
