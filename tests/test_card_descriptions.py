"""Compilation checks; runtime behavior coverage belongs to acceptance tests.

The source manifest is the independently audited factual input. These checks
catch lost mechanics, physical copies, mapping changes and descriptions that
omit important player decisions. They do not claim handlers are implemented.
"""
import json
from pathlib import Path
import re

import pytest

from dota_dungeon.cards.validation import canonical_digest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/dota_dungeon/cards/data/classic-dota-v1"
MECHANICS = (
    "deck", "kind", "value", "bonus", "slots", "size", "effects", "tags",
    "treasures", "levels", "bad_stuff", "play_phases", "target_rule",
    "restrictions", "conditions", "abilities", "trigger",
)


def compiled():
    path = DATA / "catalog.json"
    assert path.is_file(), "compiled production catalog is missing"
    return json.loads(path.read_text(encoding="utf-8"))


def source():
    return json.loads((DATA / "source-manifest.json").read_text(encoding="utf-8"))["cards"]


def test_compilation_preserves_all_verified_facts_and_accepted_mappings():
    raw = compiled()
    assert raw["version"] == "classic-dota-v1"
    assert set(raw["definitions"]) == {c["rule_key"] for c in source()}
    assert len(raw["definitions"]) == 147
    for card in source():
        definition = raw["definitions"][card["rule_key"]]
        assert definition["mechanics"] == {k: card[k] for k in MECHANICS}, card["rule_key"]
        for field in ("display_name_ru", "dota_entity_id", "source_refs"):
            assert definition["presentation"][field] == card[field], card["rule_key"]


def test_compilation_preserves_every_numbered_physical_copy_and_deck_total():
    raw = compiled()
    assert raw["instances"] == {
        f"{c['rule_key']}:{n}": c["rule_key"]
        for c in source() for n in range(1, c["copies"] + 1)
    }
    assert len(raw["instances"]) == 168
    assert {deck: sum(raw["definitions"][key]["mechanics"]["deck"] == deck
                      for key in raw["instances"].values())
            for deck in ("door", "treasure")} == {"door": 95, "treasure": 73}


def test_compilation_declares_correct_canonical_digest():
    raw = compiled()
    assert re.fullmatch(r"[0-9a-f]{64}", raw["digest"])
    assert raw["digest"] == canonical_digest(raw)


def test_every_description_is_russian_player_facing_prose():
    for key, definition in compiled()["definitions"].items():
        description = definition["presentation"]["description_ru"]
        assert len(re.findall(r"[А-Яа-яЁё]+", description)) >= 8, key
        assert not re.search(r"[a-z]+_[a-z]+|\{\s*\"|\b(?:op|args)\b", description), key
        assert "TODO" not in description and "уточняется" not in description, key


def test_items_describe_printed_value_bonus_size_and_slots():
    definitions = compiled()["definitions"]
    for card in source():
        if card["kind"] not in ("item", "one_shot"):
            continue
        description = definitions[card["rule_key"]]["presentation"]["description_ru"].lower()
        assert f"{card['value']} золотых" in description, card["rule_key"]
        if card["kind"] == "item":
            assert f"+{card['bonus']}" in description, card["rule_key"]
            assert ("большая вещь" if card["size"] == "big" else "малая вещь") in description
            slot = {None: "без слота", "head": "голова", "armor": "броня", "feet": "обувь",
                    "one_hand": "1 рука", "two_hands": "2 руки"}[card["slots"]]
            assert slot in description, card["rule_key"]


def test_monster_descriptions_show_level_rewards_and_bad_stuff():
    definitions = compiled()["definitions"]
    for card in source():
        if card["kind"] != "monster":
            continue
        description = definitions[card["rule_key"]]["presentation"]["description_ru"].lower()
        for phrase in (f"уровень {card['bonus']}", f"сокровищ: {card['treasures']}",
                       f"уровней: {card['levels']}", "непотребство"):
            assert phrase in description, (card["rule_key"], phrase)


@pytest.mark.parametrize("key,phrases", [
    ("baby", ("−5", "не ниже 1", "−1", "не меньше 1")),
    ("wizard", ("всю руку", "не меньше 3", "после броска", "без уровней", "весь бой")),
    ("thief", ("каждому", "−2", "4–6", "малую", "не участвуют в бою")),
    ("cleric", ("верхнюю", "из руки", "+3", "не более 3", "нежити")),
    ("elf", ("за каждого", "помощник", "победный")),
    ("halfling", ("одну вещь", "вдвое", "неудачного", "один повтор")),
    ("hireling", ("+1", "не вещь", "вне боя", "вместе", "одного монстра")),
    ("rat_on_a_stick", ("8", "не надета", "сбросить", "одного монстра")),
    ("kneepads_of_allure", ("строго выше", "победный", "нельзя", "клирик")),
    ("king_tut", ("2", "даже при успешном", "3", "руку", "все вещи")),
    ("wight_brothers", ("2", "даже при успешном", "уровень 1")),
    ("ghoulfiends", ("только уровни", "самого низкого")),
    ("divine_intervention", ("сразу", "все клирики", "победный", "в руке")),
    ("hoard", ("сразу", "3", "стартов", "открыто", "закрыто")),
    ("mutilate_the_bodies", ("после боя", "не требуется", "победный")),
    ("whine_at_the_gm", ("наибольший", "делишь", "победный")),
    ("magic_lamp", ("своём ходу", "неудачного", "единственный", "без уровней")),
    ("loaded_die", ("свой", "после броска", "1–6")),
    ("wand_of_dowsing", ("одну", "любого", "сброс", "одноразовая")),
    ("transferral_potion", ("другому", "весь бой", "комнату")),
    ("potion_of_halitosis", ("+2", "бэйн", "убивает")),
    ("yuppie_water", ("+2", "каждого", "эльфа")),
    ("curse_chicken_on_your_head", ("−1", "голов", "проклятие", "непотребство")),
    ("curse_malign_mirror", ("следующем бою", "брон", "бонусы")),
    ("curse_income_tax", ("стоимость", "остальные", "все вещи", "1 уровень")),
    ("curse_change_class", ("верхнюю", "сброс", "нет класса")),
    ("flask_of_glue", ("успешного", "автоматического", "повторить")),
    ("instant_wall", ("до броска", "двух")),
    ("half_breed", ("2 расы", "одной", "недостатков", "нет рас")),
    ("super_munchkin", ("2 класса", "одним", "недостатков", "нет классов")),
])
def test_distinctive_rules_are_explained_with_costs_timing_and_exceptions(key, phrases):
    description = compiled()["definitions"][key]["presentation"]["description_ru"].lower()
    for phrase in phrases:
        assert phrase in description, (key, phrase)


def test_special_timing_does_not_contradict_printed_eligibility():
    definitions = compiled()["definitions"]
    lamp = definitions["magic_lamp"]["presentation"]["description_ru"].lower()
    assert "в бою или при побеге" in lamp
    assert "вне боя" not in lamp
    after = definitions["mutilate_the_bodies"]["presentation"]["description_ru"].lower()
    assert "в любой игровой фазе" not in after
