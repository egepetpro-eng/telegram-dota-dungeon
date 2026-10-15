from datetime import datetime, timedelta, timezone
from random import Random

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command
from dota_dungeon.core.setup import new_lobby


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def all_zones(state):
    zones = state.door_deck + state.treasure_deck + state.door_discard + state.treasure_discard
    zones += [cid for player in state.players.values() for cid in player.hand + player.in_play]
    zones += [cid for cards in state.corpse.values() for cid in cards]
    if state.combat:
        zones += state.combat.monster_ids + state.combat.played_card_ids
        zones += [cid for cid in state.combat.modifier_ids if cid not in state.combat.played_card_ids]
    return zones


def test_two_player_simulation_reaches_tenth_level_only_after_monster_kill():
    catalog = load_catalog({"cards": [
        *({"id": f"d{i}", "deck": "door", "kind": "monster", "name": f"Creep {i}",
           "bonus": 0, "treasures": 0} for i in range(40)),
        *({"id": f"t{i}", "deck": "treasure", "kind": "item", "name": f"Item {i}"}
          for i in range(20)),
    ]})
    rng = Random(3)
    state = new_lobby("g", -500, 101, catalog)
    number = 0

    def step(actor, name, **args):
        nonlocal state, number
        number += 1
        state, events = decide(state, Command("g", actor, str(number), name, args), catalog, rng)
        zones = all_zones(state)
        assert len(zones) == len(set(zones)) == len(catalog)
        return events

    for user in (101, 102):
        step(user, "join")
        step(user, "ready", ready=True)
    step(101, "start")
    first = state.active_user_id
    for turn in range(17):
        actor = state.active_user_id
        step(actor, "open_door")
        assert state.phase == "combat.active"
        step(actor, "declare_win", now=NOW)
        step(actor, "close_reaction", now=NOW + timedelta(seconds=31))
        if state.phase == "game.finished":
            break
        assert state.players[actor].level < 10
        if len(state.players[actor].hand) > 5:
            minimum = min(p.level for p in state.players.values())
            if state.players[actor].level == minimum:
                assignments = {}
            else:
                recipient = next(u for u, p in state.players.items() if p.level == minimum)
                excess = state.players[actor].hand[5:]
                assignments = {recipient: excess}
            step(actor, "give_charity", assignments=assignments,
                 discard_ids=state.players[actor].hand[5:] if not assignments else [])
        step(actor, "end_turn")
    assert state.phase == "game.finished"
    assert state.players[first].level == 10
