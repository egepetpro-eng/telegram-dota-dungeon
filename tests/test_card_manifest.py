"""Check the research artifact against an independently captured publisher checklist.

Unresolved research remains useful, but must never masquerade as verified rules.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "src/dota_dungeon/cards/data/classic-dota-v1/source-manifest.json"
CHECKLIST = ROOT / "tests/fixtures/classic-checklist.json"
MECHANICS = ("deck", "kind", "value", "bonus", "slots", "size", "effects", "tags",
             "treasures", "levels", "bad_stuff", "play_phases", "target_rule",
             "restrictions", "conditions", "abilities", "trigger")


def cards():
    assert MANIFEST.is_file(), "source manifest has not been created"
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["cards"]


def test_source_manifest_has_168_physical_cards():
    records = cards()
    assert sum(card["copies"] for card in records) == 168
    assert {deck: sum(c["copies"] for c in records if c["deck"] == deck)
            for deck in ("door", "treasure")} == {"door": 95, "treasure": 73}


def test_manifest_preserves_official_copy_counts():
    records = cards()
    official = json.loads(CHECKLIST.read_text(encoding="utf-8"))
    for deck in ("door", "treasure"):
        actual = Counter()
        for card in records:
            if card["deck"] == deck:
                actual[card["source_name"]] += card["copies"]
        assert actual == Counter(official["decks"][deck])


def test_every_definition_has_verified_evidence():
    records = cards()
    assert len({c["rule_key"] for c in records}) == len(records)
    for card in records:
        assert type(card["copies"]) is int and card["copies"] > 0
        assert card["source_refs"] and all(card["source_refs"])
        assert card["verified_on"] == "2026-10-08"
        assert card["evidence_status"] == "verified"
        assert card["evidence_notes"].strip()
        assert all(key in card for key in MECHANICS)
        if card["evidence_status"] == "unresolved":
            assert "unresolved:" in card["evidence_notes"].lower()
        else:
            assert "unresolved:" not in card["evidence_notes"].lower()
            assert all(type(card[key]) is int for key in
                       ("value", "bonus", "treasures", "levels"))
            assert all(card[key] is not None for key in
                       ("effects", "tags", "bad_stuff", "play_phases",
                        "restrictions", "conditions", "abilities"))


def test_dota_names_do_not_control_mechanical_keys():
    records = cards()
    renamed = deepcopy(records)
    for record in renamed:
        record["display_name_ru"] = "Другое название"
    assert [(c["rule_key"], {k: c[k] for k in MECHANICS}) for c in records] == [
        (c["rule_key"], {k: c[k] for k in MECHANICS}) for c in renamed]
    classes = {c["rule_key"]: c["dota_entity_id"] for c in records if c["kind"] == "role"}
    assert classes["warrior"] == "hero:axe"
    assert classes["thief"] == "hero:riki"
    assert len(set(classes.values())) == 4


def test_primary_numeric_facts_preserved_without_dota_repricing():
    by_key = {c["rule_key"]: c for c in cards()}
    assert by_key["net_troll"]["bonus"] == 10
    assert by_key["net_troll"]["treasures"] == 3
    assert by_key["chainsaw_of_bloody_dismemberment"]["bonus"] == 3
    assert by_key["magic_missile"]["effects"] == [{"op": "add_strength", "amount": 5}]
    assert by_key["enraged"]["effects"] == [
        {"op": "monster_modifier", "amount": 5, "treasures": 1}]
    assert by_key["boots_of_butt_kicking"]["bonus"] == 2
    assert by_key["swiss_army_polearm"]["slots"] == "two_hands"
    assert by_key["floating_nose"]["bad_stuff"] == [{"op": "lose_level", "amount": 3}]
    assert by_key["mr_bones"]["tags"] == ["undead"]
    assert by_key["hoard"]["effects"] == [{"op": "draw", "deck": "treasure", "amount": 3}]


def test_inspected_card_faces_supply_prices_and_restrictions():
    by_key = {c["rule_key"]: c for c in cards()}
    assert by_key["magic_missile"]["value"] == 300
    assert by_key["boots_of_butt_kicking"]["value"] == 400
    assert by_key["chainsaw_of_bloody_dismemberment"]["value"] == 600
    assert by_key["wand_of_dowsing"]["value"] == 1100
    assert by_key["pollymorph_potion"]["value"] == 1300
    assert by_key["huge_rock"]["value"] == 0
    assert by_key["huge_rock"]["size"] == "big"
    assert by_key["broad_sword"]["restrictions"] == {"sex": "female"}
    assert by_key["wizard"]["abilities"][1]["cost"] == {
        "zone": "hand", "count": 3, "mode": "all_hand"}
    assert by_key["mutilate_the_bodies"]["conditions"] == [
        {"rule_key": "after_combat", "args": {}}]


def test_conditional_escape_is_an_ability_not_an_equip_effect():
    by_key = {c["rule_key"]: c for c in cards()}
    rat = by_key["rat_on_a_stick"]
    assert rat["effects"] == []
    assert rat["abilities"] == [{
        "key": "rat_on_a_stick_escape",
        "cost": {"zone": "in_play", "count": 1},
        "limit": {"scope": "escape_attempt", "max_uses": 1},
        "phases": ["combat.run_away"],
    }]
    assert rat["conditions"] == [{
        "rule_key": "rat_escape_eligibility",
        "args": {"maximum_monster_level": 8, "usable_unequipped": True}}]
    assert by_key["shield_of_ubiquity"]["value"] == 600
    assert by_key["shield_of_ubiquity"]["size"] == "big"
    assert by_key["plutonium_dragon"]["dota_entity_id"] == "creep:roshan"
    assert len({c["dota_entity_id"] for c in cards()
                if c["dota_entity_id"].startswith("creep:")}) >= 5
