import pytest

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.model import GameState, Player, RuleError
from dota_dungeon.core.turn import end_turn, give_charity, loot_room, open_door, seek_trouble


def scenario(door_kind="role"):
    cards = [
        {"id": "door", "deck": "door", "kind": door_kind, "name": "Door", "bonus": 3,
         "effects": [{"op": "lose_level", "amount": 1}] if door_kind == "curse" else []},
        {"id": "room", "deck": "door", "kind": "monster", "name": "Room creep", "bonus": 2},
        {"id": "hand-monster", "deck": "door", "kind": "monster", "name": "Hand creep", "bonus": 2},
    ]
    catalog = load_catalog({"cards": cards})
    state = GameState("g", -500, 101, "turn.prepare", 101, [101, 102],
                      {101: Player(101, level=2, hand=["hand-monster"]), 102: Player(102) },
                      door_deck=["room", "door"])
    state.card_decks = {cid: card.deck for cid, card in catalog.items()}
    return state, catalog


def test_open_monster_is_public_and_enters_combat():
    state, catalog = scenario("monster")
    state, events = open_door(state, 101, catalog)
    assert state.phase == "combat.active"
    assert state.combat.monster_ids == ["door"]
    assert any(e.name == "door.revealed" and e.audience == "group" for e in events)


def test_curse_applies_immediately_and_is_discarded():
    state, catalog = scenario("curse")
    state, events = open_door(state, 101, catalog)
    assert state.players[101].level == 1
    assert state.door_discard == ["door"]
    assert state.phase == "turn.after_door"
    assert any(e.name == "curse.applied" for e in events)


def test_room_loot_is_private_after_nonmonster_door():
    state, catalog = scenario()
    state, _ = open_door(state, 101, catalog)
    state, events = loot_room(state, 101)
    assert state.phase == "turn.charity"
    assert "room" in state.players[101].hand
    assert any(e.name == "card.drawn" and e.audience == "user:101" for e in events)
    assert not any(e.name == "card.drawn" and e.audience == "group" for e in events)


def test_cannot_loot_room_after_monster():
    state, catalog = scenario("monster")
    state, _ = open_door(state, 101, catalog)
    with pytest.raises(RuleError):
        loot_room(state, 101)


def test_seek_trouble_uses_monster_from_hand():
    state, catalog = scenario()
    state, _ = open_door(state, 101, catalog)
    state, _ = seek_trouble(state, 101, "hand-monster", catalog)
    assert state.combat.monster_ids == ["hand-monster"]
    assert "hand-monster" not in state.players[101].hand


def charity_game(levels, hand):
    players = {user: Player(user, level=level) for user, level in levels.items()}
    players[101].hand = hand.copy()
    state = GameState("g", -500, 101, "turn.charity", 101, list(levels), players)
    state.card_decks = {cid: "door" for cid in hand}
    return state


def test_lowest_level_actor_discards_excess():
    state = charity_game({101: 1, 102: 1}, list("abcdef"))
    state, events = give_charity(state, 101, {})
    assert len(state.players[101].hand) == 5
    assert len(state.players[102].hand) == 0
    assert len(state.door_discard) == 1
    assert any(e.name == "charity.discarded" for e in events)


def test_unique_lower_level_player_receives_excess():
    state = charity_game({101: 2, 102: 1}, list("abcdef"))
    state, _ = give_charity(state, 101, {102: ["a"]})
    assert len(state.players[101].hand) == 5
    assert state.players[102].hand == ["a"]


def test_tied_lowest_recipients_receive_even_distribution():
    state = charity_game({101: 3, 102: 1, 103: 1}, list("abcdefgh"))
    state, _ = give_charity(state, 101, {102: ["a", "b"], 103: ["c"]})
    assert len(state.players[101].hand) == 5
    assert len(state.players[102].hand) == 2
    assert len(state.players[103].hand) == 1


def test_end_turn_requires_hand_limit():
    state = charity_game({101: 1, 102: 1}, list("abcdef"))
    with pytest.raises(RuleError, match="five"):
        end_turn(state, 101)


def test_empty_door_stack_recycles_discard_before_opening():
    state, catalog = scenario()
    state.door_deck = []
    state.door_discard = ["door"]
    state, events = open_door(state, 101, catalog)
    assert state.door_discard == []
    assert any(e.name == "door.revealed" for e in events)
