import pytest

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.items import equip, sell, unequip
from dota_dungeon.core.model import GameState, Player, RuleError


def gear_game(level=1):
    entries = [
        ("head-a", "head", 100, 1), ("head-b", "head", 100, 1),
        ("armor-a", "armor", 100, 1), ("armor-b", "armor", 100, 1),
        ("feet-a", "footwear", 100, 1), ("feet-b", "footwear", 100, 1),
        ("hand-a", "one_hand", 100, 1), ("hand-b", "one_hand", 100, 1),
        ("hand-c", "one_hand", 100, 1), ("two-hand", "two_hands", 100, 2),
        ("cheap", None, 900, 0), ("valuable", None, 1100, 0),
        ("very-valuable", None, 2000, 0),
    ]
    catalog = load_catalog({"cards": [
        {"id": card_id, "deck": "treasure", "kind": "item", "name": card_id,
         "slots": slot, "value": value, "bonus": bonus}
        for card_id, slot, value, bonus in entries
    ]})
    state = GameState("g", -500, 101, "turn.prepare", 101, [101, 102],
                      {101: Player(101, level=level, hand=list(catalog)), 102: Player(102)})
    return state, catalog


@pytest.mark.parametrize("first,second,match", [
    ("head-a", "head-b", "head slot"), ("armor-a", "armor-b", "armor slot"),
    ("feet-a", "feet-b", "footwear slot"),
    ("two-hand", "hand-a", "hand slots"),
])
def test_slot_limits(first, second, match):
    state, catalog = gear_game()
    state, _ = equip(state, 101, first, catalog)
    with pytest.raises(RuleError, match=match):
        equip(state, 101, second, catalog)


def test_two_one_hand_items_fit_but_third_does_not():
    state, catalog = gear_game()
    state, _ = equip(state, 101, "hand-a", catalog)
    state, _ = equip(state, 101, "hand-b", catalog)
    assert len(state.players[101].equipped) == 2
    with pytest.raises(RuleError, match="hand slots"):
        equip(state, 101, "hand-c", catalog)


def test_unequipped_carried_item_stays_open_without_bonus():
    state, catalog = gear_game()
    state, _ = equip(state, 101, "head-a", catalog)
    state, _ = unequip(state, 101, "head-a")
    assert "head-a" in state.players[101].in_play
    assert "head-a" not in state.players[101].equipped


@pytest.mark.parametrize("card_ids,gain", [
    (["valuable"], 1), (["very-valuable"], 2),
])
def test_sale_grants_whole_levels_without_change(card_ids, gain):
    state, catalog = gear_game()
    state, _ = sell(state, 101, card_ids, catalog)
    assert state.players[101].level == 1 + gain
    assert set(card_ids).issubset(state.treasure_discard)


def test_sale_under_1000_is_rejected():
    state, catalog = gear_game()
    with pytest.raises(RuleError):
        sell(state, 101, ["cheap"], catalog)


def test_sale_cannot_grant_level_ten_and_retains_items():
    state, catalog = gear_game(level=9)
    with pytest.raises(RuleError, match="winning level"):
        sell(state, 101, ["valuable"], catalog)
    assert "valuable" in state.players[101].hand


def test_sale_requires_own_turn_outside_combat():
    state, catalog = gear_game()
    state.phase = "combat.active"
    with pytest.raises(RuleError, match="outside combat"):
        sell(state, 101, ["valuable"], catalog)
