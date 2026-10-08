from datetime import datetime, timedelta, timezone
from random import Random

import pytest

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command, RuleError
from dota_dungeon.core.setup import new_lobby


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def catalog_with_roles():
    return load_catalog({"cards": [
        *({"id": f"d{i}", "deck": "door", "kind": "role", "name": f"Hero {i}"}
          for i in range(24)),
        *({"id": f"t{i}", "deck": "treasure", "kind": "item", "name": f"Item {i}"}
          for i in range(24)),
    ]})


def do(state, catalog, rng, request_id, actor, name, **args):
    return decide(state, Command(state.game_id, actor, request_id, name, args), catalog, rng)


def started_game(catalog, rng):
    state = new_lobby("g", -500, 101, catalog)
    for user in (101, 102):
        state, _ = do(state, catalog, rng, f"join-{user}", user, "join")
        state, _ = do(state, catalog, rng, f"ready-{user}", user, "ready", ready=True)
    return do(state, catalog, rng, "start", 101, "start")


def test_end_to_end_nonmonster_turn_keeps_hidden_draw_private():
    catalog = catalog_with_roles()
    rng = Random(4)
    state, events = started_game(catalog, rng)
    assert any(e.name == "game.started" and e.audience == "group" for e in events)
    assert all(e.audience != "group" for e in events if e.name == "hand.dealt")
    actor = state.active_user_id
    state, events = do(state, catalog, rng, "door", actor, "open_door")
    assert sum(e.name == "door.revealed" and e.audience == "group" for e in events) == 1
    state, events = do(state, catalog, rng, "loot", actor, "loot_room")
    assert any(e.name == "card.drawn" and e.audience == f"user:{actor}" for e in events)
    assert not any(e.name == "card.drawn" and e.audience == "group" for e in events)
    state, _ = do(state, catalog, rng, "charity", actor, "give_charity", assignments={})
    state, events = do(state, catalog, rng, "end", actor, "end_turn")
    assert state.active_user_id != actor
    assert any(e.name == "turn.started" and e.audience == "group" for e in events)


def test_wrong_game_unknown_command_and_wrong_actor_rejected():
    catalog = catalog_with_roles()
    rng = Random(4)
    state, _ = started_game(catalog, rng)
    with pytest.raises(RuleError, match="another game"):
        decide(state, Command("other", state.active_user_id, "x", "open_door"), catalog, rng)
    with pytest.raises(RuleError, match="unknown command"):
        do(state, catalog, rng, "x", state.active_user_id, "teleport")
    other = next(user for user in state.order if user != state.active_user_id)
    with pytest.raises(RuleError, match="not your turn"):
        do(state, catalog, rng, "x", other, "open_door")


def test_repeated_open_door_request_does_not_draw_twice():
    catalog = catalog_with_roles()
    rng = Random(4)
    state, _ = started_game(catalog, rng)
    actor = state.active_user_id
    state, _ = do(state, catalog, rng, "door", actor, "open_door")
    count = len(state.door_deck)
    state, events = do(state, catalog, rng, "door", actor, "open_door")
    assert len(state.door_deck) == count
    assert events == []


def test_repeated_sale_request_cannot_remove_items_twice():
    catalog = catalog_with_roles()
    catalog["t0"] = catalog["t0"].__class__("t0", "treasure", "item", "Valuable", value=1000)
    rng = Random(4)
    state, _ = started_game(catalog, rng)
    actor = state.active_user_id
    # Move a known physical item to the actor's hand from its existing zone.
    for player in state.players.values():
        if "t0" in player.hand:
            player.hand.remove("t0")
    if "t0" in state.treasure_deck:
        state.treasure_deck.remove("t0")
    state.players[actor].hand.append("t0")
    state, _ = do(state, catalog, rng, "sale", actor, "sell", card_ids=["t0"])
    state, events = do(state, catalog, rng, "sale", actor, "sell", card_ids=["t0"])
    assert state.players[actor].level == 2
    assert state.treasure_discard.count("t0") == 1
    assert events == []
