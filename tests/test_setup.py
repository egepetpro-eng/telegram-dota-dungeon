from random import Random

import pytest

from dota_dungeon.core.model import RuleError
from dota_dungeon.core.setup import join, new_lobby, set_ready, start
from fixtures import small_catalog


def ready_lobby(count, catalog):
    state = new_lobby("g", -500, 101, catalog)
    for user_id in range(101, 101 + count):
        state, _ = join(state, user_id)
        state, _ = set_ready(state, user_id, True)
    return state


@pytest.mark.parametrize("count", [2, 6])
def test_ready_players_start_with_four_cards_from_each_deck(count):
    catalog = small_catalog()
    lobby = ready_lobby(count, catalog)
    state, events = start(lobby, lobby.host_id, catalog, Random(7))
    assert state.phase == "turn.prepare"
    assert len(state.order) == count
    assert all(len(state.players[u].hand) == 8 for u in state.order)
    assert all(state.players[u].level == 1 for u in state.order)
    assert all(event.audience != "group" for event in events if event.name == "hand.dealt")


def test_one_player_cannot_start():
    catalog = small_catalog()
    lobby = ready_lobby(1, catalog)
    with pytest.raises(RuleError, match="2 to 6"):
        start(lobby, lobby.host_id, catalog, Random(7))


def test_seventh_player_cannot_join():
    catalog = small_catalog()
    lobby = ready_lobby(6, catalog)
    with pytest.raises(RuleError, match="full"):
        join(lobby, 107)


def test_unready_player_blocks_start():
    catalog = small_catalog()
    lobby = ready_lobby(2, catalog)
    lobby, _ = set_ready(lobby, 102, False)
    with pytest.raises(RuleError, match="ready"):
        start(lobby, lobby.host_id, catalog, Random(7))


def test_seed_reproduces_deck_order_and_every_card_has_one_zone():
    catalog = small_catalog()
    lobby = ready_lobby(6, catalog)
    a, _ = start(lobby, 101, catalog, Random(9))
    b, _ = start(lobby, 101, catalog, Random(9))
    assert a.door_deck == b.door_deck
    assert a.treasure_deck == b.treasure_deck
    assert a.active_user_id == b.active_user_id
    zones = a.door_deck + a.treasure_deck + [c for p in a.players.values() for c in p.hand]
    assert len(zones) == len(set(zones)) == len(catalog)
