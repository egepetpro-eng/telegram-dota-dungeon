"""Verified release boundaries, using only the coordinator's synthetic fixture."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.items import equip
from dota_dungeon.core.model import CombatState, GameState, Player, RuleError


FIXTURE = Path(__file__).parent / "fixtures" / "catalog-contract-v1.json"


def fixture_pair():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    records = []
    for key, definition in raw["definitions"].items():
        records.append({
            "rule_key": key, "copies": sum(v == key for v in raw["instances"].values()),
            "source_name": f"Synthetic {key}", **deepcopy(definition["mechanics"]),
            "source_refs": ["fixture:synthetic"], "verified_on": "2026-10-08",
            "dota_entity_id": definition["presentation"]["dota_entity_id"],
            "display_name_ru": definition["presentation"]["display_name_ru"],
            "evidence_status": "verified", "evidence_notes": "Synthetic test facts only",
        })
    return raw, {"version": raw["version"], "cards": records}


def validate(raw, manifest):
    from dota_dungeon.cards.validation import validate_release
    validate_release(raw, manifest)


def write_release(tmp_path, raw, manifest):
    path = tmp_path / "release.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "source-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def load(path):
    from dota_dungeon.cards.release import load_release
    return load_release(path)


def mutate_mechanic(raw, manifest, field, value, key="fixture_item"):
    raw["definitions"][key]["mechanics"][field] = value
    next(record for record in manifest["cards"] if record["rule_key"] == key)[field] = deepcopy(value)


def test_two_copies_load_with_same_rule_but_independent_physical_zones(tmp_path):
    raw, manifest = fixture_pair()
    release = load(write_release(tmp_path, raw, manifest))
    assert release.version == "synthetic-contract-v1"
    assert len(release.catalog) == 4
    first, second = release.catalog["fixture_item:1"], release.catalog["fixture_item:2"]
    assert first.rule_key == second.rule_key == "fixture_item"
    assert (first.bonus, first.value, first.slots) == (2, 300, "one_hand")
    assert first.play_phases == ("turn.prepare",)
    assert first.target_rule == "self"
    assert release.presentations[first.id].source_refs == ("fixture:synthetic",)
    assert release.presentations[first.id].display_name_ru == "Тестовый предмет"
    state = GameState("g", -1, 1, "turn.prepare", 1, [1, 2], {
        1: Player(1, hand=[first.id]), 2: Player(2, hand=[second.id])})
    after, _ = equip(state, 1, first.id, release.catalog)
    assert after.players[1].in_play == ["fixture_item:1"]
    assert after.players[2].hand == ["fixture_item:2"]
    assert state.players[1].hand == ["fixture_item:1"]


def test_digest_is_canonical_utf8_and_excludes_declared_digest(tmp_path):
    raw, manifest = fixture_pair()
    expected = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False).encode("utf-8")).hexdigest()
    raw["digest"] = expected
    release = load(write_release(tmp_path, raw, manifest))
    assert release.digest == expected
    raw["digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        validate(raw, manifest)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_definition", "wrong_number"])
def test_rejects_inexact_physical_instances(mutation):
    raw, manifest = fixture_pair()
    if mutation == "missing":
        del raw["instances"]["fixture_item:2"]
    elif mutation == "extra":
        raw["instances"]["fixture_item:3"] = "fixture_item"
    elif mutation == "wrong_definition":
        raw["instances"]["fixture_item:2"] = "fixture_level"
    else:
        raw["instances"]["fixture_item:02"] = raw["instances"].pop("fixture_item:2")
    with pytest.raises(ValueError, match="instance|cop"):
        validate(raw, manifest)


def test_loader_rejects_duplicate_json_physical_ids(tmp_path):
    raw, manifest = fixture_pair()
    path = write_release(tmp_path, raw, manifest)
    text = path.read_text(encoding="utf-8")
    text = text.replace('"fixture_item:1": "fixture_item"',
                        '"fixture_item:1": "fixture_item", "fixture_item:1": "fixture_item"')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load(path)


@pytest.mark.parametrize("field,value", [
    ("value", 301), ("bonus", 3), ("slots", "head"), ("size", "big"),
    ("tags", ["warrior"]), ("play_phases", ["turn.after_door"]),
    ("target_rule", "player"), ("restrictions", {"sex": "male"}),
    ("effects", [{"op": "add_strength", "amount": 2}]), ("treasures", 2),
    ("levels", 2), ("bad_stuff", [{"op": "lose_level", "amount": 2}]),
])
def test_rejects_changed_source_mechanics(field, value):
    raw, manifest = fixture_pair()
    raw["definitions"]["fixture_item"]["mechanics"][field] = value
    with pytest.raises(ValueError, match="mechanics|source"):
        validate(raw, manifest)


@pytest.mark.parametrize("field,value", [
    ("value", True), ("value", -1), ("value", 1.5), ("bonus", False),
    ("bonus", "2"), ("treasures", True), ("treasures", -1),
    ("levels", False), ("levels", 0), ("levels", 1.0),
    ("deck", "other"), ("deck", []), ("kind", "other"),
    ("slots", "footwear"), ("size", "large"), ("tags", ["elf", "elf"]),
    ("tags", [1]), ("play_phases", ["lobby"]),
    ("play_phases", ["turn.prepare", "turn.prepare"]),
    ("target_rule", "hand"), ("target_rule", {}),
    ("restrictions", {"sex": "other"}), ("restrictions", {"carry_limit": 2}),
    ("restrictions", {"role_any": ["warrior", "warrior"]}),
    ("restrictions", {"requires_rule": ""}),
    ("conditions", [{"rule_key": "undeclared", "args": {}}]),
    ("trigger", {"rule_key": "undeclared", "timing": "acquired", "visibility": "group", "args": {}}),
    ("abilities", [{"key": "undeclared", "cost": {"zone": "hand", "count": 1},
                    "limit": {"scope": "turn", "max_uses": 1}, "phases": ["turn.prepare"]}]),
    ("invented_field", 1),
])
def test_rejects_invalid_mechanics_even_when_source_agrees(field, value):
    raw, manifest = fixture_pair()
    mutate_mechanic(raw, manifest, field, value)
    with pytest.raises(ValueError):
        validate(raw, manifest)


@pytest.mark.parametrize("effect", [
    {"op": "gain_level", "amount": True}, {"op": "lose_level", "amount": 0},
    {"op": "draw", "amount": 1.0}, {"op": "draw", "deck": "other"},
    {"op": "add_strength", "amount": False}, {"op": "monster_modifier", "amount": "2"},
    {"op": "escape_modifier", "amount": 1.5}, {"op": "gain_level", "can_win": 1},
    {"op": "remove_item"}, {"op": "remove_item", "card_id": 1},
    {"op": "persistent", "card_id": ""}, {"op": "kill_monster"},
    {"op": "remove_monster", "monster_id": False}, {"op": "prevent_bad_stuff", "monster_id": []},
    {"op": "arbitrary_python"}, {"op": "gain_level", "effects": [{"op": "arbitrary_python"}]},
    {"op": "special", "rule_key": "declared_only", "args": {}},
    {"op": "special", "rule_key": "declared_only", "args": {"op": "arbitrary_python"}},
])
@pytest.mark.parametrize("field", ["effects", "bad_stuff"])
def test_rejects_every_invalid_operation_including_bad_stuff(field, effect):
    raw, manifest = fixture_pair()
    mutate_mechanic(raw, manifest, field, [effect])
    with pytest.raises(ValueError):
        validate(raw, manifest)


@pytest.mark.parametrize("field,value", [
    ("copies", True), ("copies", 0), ("copies", 2.0),
    ("evidence_status", "unresolved"), ("evidence_status", None),
    ("source_name", ""), ("source_refs", []), ("verified_on", "2026-02-30"),
    ("dota_entity_id", ""), ("evidence_notes", 1), ("unknown", "x"),
])
def test_rejects_invalid_or_unverified_source_record(field, value):
    raw, manifest = fixture_pair()
    manifest["cards"][0][field] = value
    with pytest.raises(ValueError):
        validate(raw, manifest)


def test_rejects_missing_source_evidence_status():
    raw, manifest = fixture_pair()
    del manifest["cards"][0]["evidence_status"]
    with pytest.raises(ValueError, match="evidence"):
        validate(raw, manifest)


@pytest.mark.parametrize("mutation", ["missing_definition", "extra_definition", "duplicate_source", "version"])
def test_release_and_source_must_describe_exactly_the_same_definitions(mutation):
    raw, manifest = fixture_pair()
    if mutation == "missing_definition":
        del raw["definitions"]["fixture_level"]
    elif mutation == "extra_definition":
        raw["definitions"]["extra"] = deepcopy(raw["definitions"]["fixture_level"])
    elif mutation == "duplicate_source":
        manifest["cards"].append(deepcopy(manifest["cards"][0]))
    else:
        manifest["version"] = "other-version"
    with pytest.raises(ValueError):
        validate(raw, manifest)


@pytest.mark.parametrize("field,value", [
    ("display_name_ru", ""), ("description_ru", ""), ("dota_entity_id", 1),
    ("source_refs", []), ("source_refs", [""]), ("source_refs", "source"), ("extra", 1),
])
def test_rejects_invalid_presentation(field, value):
    raw, manifest = fixture_pair()
    raw["definitions"]["fixture_item"]["presentation"][field] = value
    with pytest.raises(ValueError):
        validate(raw, manifest)


def test_presentation_changes_do_not_control_source_rule_comparison(tmp_path):
    raw, manifest = fixture_pair()
    raw["definitions"]["fixture_item"]["presentation"]["display_name_ru"] = "Другое имя"
    release = load(write_release(tmp_path, raw, manifest))
    assert release.catalog["fixture_item:1"].bonus == 2
    assert release.presentations["fixture_item:1"].display_name_ru == "Другое имя"


def test_feet_slot_adapter_enforces_actual_equipment_capacity(tmp_path):
    raw, manifest = fixture_pair()
    mutate_mechanic(raw, manifest, "slots", "feet")
    release = load(write_release(tmp_path, raw, manifest))
    state = GameState("g", -1, 1, "turn.prepare", 1, [1], {
        1: Player(1, hand=["fixture_item:1", "fixture_item:2"])})
    state, _ = equip(state, 1, "fixture_item:1", release.catalog)
    with pytest.raises(RuleError, match="footwear slot"):
        equip(state, 1, "fixture_item:2", release.catalog)


def test_legacy_catalog_defaults_and_new_empty_combat_zone():
    catalog = load_catalog({"cards": [{"id": "old", "deck": "door", "kind": "monster", "name": "Old"}]})
    card = catalog["old"]
    assert card.rule_key is None
    assert card.play_phases == ()
    assert card.target_rule == "none"
    assert card.restrictions == {}
    assert card.conditions == [] and card.abilities == [] and card.trigger is None
    state = GameState("g", -1, 1, "lobby", None, [], {})
    assert state.catalog_version is None and state.catalog_digest is None
    one, two = CombatState(), CombatState()
    one.played_card_ids.append("old")
    assert two.played_card_ids == []


def test_generic_operations_accept_verified_operands_and_signed_strength(tmp_path):
    raw, manifest = fixture_pair()
    operations = [
        {"op": "gain_level", "can_win": True}, {"op": "lose_level"}, {"op": "draw"},
        {"op": "add_strength", "amount": -2}, {"op": "monster_modifier", "amount": 0},
        {"op": "escape_modifier", "amount": -1},
        {"op": "remove_item", "card_id": "fixture_item:1"},
        {"op": "persistent", "card_id": "fixture_item:1"},
        {"op": "kill_monster", "monster_id": "fixture_monster:1"},
        {"op": "remove_monster", "monster_id": "fixture_monster:1"},
        {"op": "prevent_bad_stuff", "monster_id": "fixture_monster:1"},
    ]
    mutate_mechanic(raw, manifest, "effects", operations)
    release = load(write_release(tmp_path, raw, manifest))
    assert release.catalog["fixture_item:1"].effects == operations
    # Mutable descriptors from separate physical cards must never share storage.
    release.catalog["fixture_item:1"].effects[3]["amount"] = 99
    assert release.catalog["fixture_item:2"].effects[3]["amount"] == -2


def test_registered_rules_preserve_descriptors_and_validate_closed_args(tmp_path, monkeypatch):
    from dota_dungeon.core import card_rules
    raw, manifest = fixture_pair()

    def checked_args(args):
        if args != {"amount": 2}:
            raise ValueError("unsupported handler args")

    def checked_ability(descriptor):
        if descriptor["cost"]["count"] != 1:
            raise ValueError("unsupported ability cost")

    handler = lambda *args: None
    for registry in (card_rules.SPECIAL_HANDLERS, card_rules.CONDITION_HANDLERS,
                     card_rules.TRIGGER_HANDLERS):
        monkeypatch.setitem(registry, "fixture_rule", card_rules.RegisteredRule(handler, checked_args))
    monkeypatch.setitem(card_rules.ABILITY_HANDLERS, "fixture_ability",
                        card_rules.RegisteredRule(handler, checked_ability))
    descriptors = {
        "effects": [{"op": "special", "rule_key": "fixture_rule", "args": {"amount": 2}}],
        "conditions": [{"rule_key": "fixture_rule", "args": {"amount": 2}}],
        "trigger": {"rule_key": "fixture_rule", "timing": "initial_deal", "visibility": "inherit", "args": {"amount": 2}},
        "abilities": [{"key": "fixture_ability", "cost": {"zone": "either", "count": 1},
                       "limit": {"scope": "unlimited", "max_uses": None}, "phases": ["combat.active"]}],
        "restrictions": {"role_any": ["warrior"], "race_any": ["elf"], "cannot_use_roles": ["cleric"],
                         "cannot_use_races": ["dwarf"], "sex": "female", "requires_rule": "fixture_rule"},
    }
    for field, value in descriptors.items():
        mutate_mechanic(raw, manifest, field, value)
    release = load(write_release(tmp_path, raw, manifest))
    card = release.catalog["fixture_item:1"]
    for field, value in descriptors.items():
        assert getattr(card, field) == value
    mutate_mechanic(raw, manifest, "effects", [{"op": "special", "rule_key": "fixture_rule", "args": {"unexpected": 2}}])
    with pytest.raises(ValueError, match="args"):
        validate(raw, manifest)


@pytest.mark.parametrize("part,field,value", [
    ("cost", "count", True), ("cost", "count", -1), ("cost", "zone", "deck"),
    ("cost", "extra", 1), ("limit", "max_uses", True), ("limit", "max_uses", 0),
    ("limit", "scope", "game"), ("limit", "extra", 1),
    (None, "phases", ["game.finished"]), (None, "extra", 1),
])
def test_registered_abilities_still_enforce_descriptor_schema(part, field, value, monkeypatch):
    from dota_dungeon.core import card_rules
    monkeypatch.setitem(card_rules.ABILITY_HANDLERS, "fixture_ability",
                        card_rules.RegisteredRule(lambda *args: None, lambda args: None))
    raw, manifest = fixture_pair()
    ability = {"key": "fixture_ability", "cost": {"zone": "hand", "count": 0},
               "limit": {"scope": "turn", "max_uses": 1}, "phases": ["turn.prepare"]}
    (ability[part] if part else ability)[field] = value
    mutate_mechanic(raw, manifest, "abilities", [ability])
    with pytest.raises(ValueError):
        validate(raw, manifest)


@pytest.mark.parametrize("field,value", [
    ("timing", "combat"), ("visibility", "hidden"), ("args", []), ("extra", 1),
])
def test_registered_triggers_still_enforce_descriptor_schema(field, value, monkeypatch):
    from dota_dungeon.core import card_rules
    monkeypatch.setitem(card_rules.TRIGGER_HANDLERS, "fixture_rule",
                        card_rules.RegisteredRule(lambda *args: None, lambda args: None))
    raw, manifest = fixture_pair()
    trigger = {"rule_key": "fixture_rule", "timing": "acquired", "visibility": "group", "args": {}}
    trigger[field] = value
    mutate_mechanic(raw, manifest, "trigger", trigger)
    with pytest.raises(ValueError):
        validate(raw, manifest)


@pytest.mark.parametrize("side,field,value", [
    ("release", "definitions", []), ("release", "instances", []), ("release", "extra", 1),
    ("release", "version", ""), ("release", "digest", True),
    ("manifest", "cards", []), ("manifest", "cards", {}), ("manifest", "extra", 1),
])
def test_rejects_invalid_release_or_manifest_shape(side, field, value):
    raw, manifest = fixture_pair()
    (raw if side == "release" else manifest)[field] = value
    with pytest.raises(ValueError):
        validate(raw, manifest)
