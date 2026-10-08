from datetime import datetime, timedelta, timezone
from random import Random

import pytest

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.combat import (
    accept_help, ask_help, begin_escape, close_reaction, combat_strength,
    declare_result, declare_win, loot_corpse, play_combat_card, resolve_rewards,
    run_away,
)
from dota_dungeon.core.model import CardDef, CombatState, GameState, Player, RuleError
from dota_dungeon.core.turn import end_turn


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class FixedDie:
    def __init__(self, *values):
        self.values = iter(values)

    def randint(self, low, high):
        return next(self.values)


def combat_game(monster_level=2, second=False, player_level=3):
    catalog = load_catalog({"cards": [
        {"id": "m1", "deck": "door", "kind": "monster", "name": "Creep", "bonus": monster_level,
         "treasures": 2, "bad_stuff": [{"op": "lose_level", "amount": 1}]},
        {"id": "m2", "deck": "door", "kind": "monster", "name": "Second creep", "bonus": 2,
         "treasures": 1, "bad_stuff": [{"op": "lose_level", "amount": 1}]},
        {"id": "hat", "deck": "treasure", "kind": "item", "name": "Hat", "bonus": 2, "slots": "head"},
        {"id": "role", "deck": "door", "kind": "role", "name": "Role", "bonus": 1},
        {"id": "buff", "deck": "treasure", "kind": "one_shot", "name": "Buff",
         "effects": [{"op": "add_strength", "amount": 3}]},
        {"id": "debuff", "deck": "door", "kind": "modifier", "name": "Debuff", "bonus": 6},
        *({"id": f"t{i}", "deck": "treasure", "kind": "item", "name": f"T{i}"} for i in range(5)),
    ]})
    players = {
        101: Player(101, level=player_level, in_play=["hat", "role"], equipped=["hat"], role_ids=["role"]),
        102: Player(102, level=2),
        103: Player(103, level=1, hand=["debuff"]),
    }
    monsters = ["m1", "m2"] if second else ["m1"]
    state = GameState("g", -500, 101, "combat.active", 101, [101, 102, 103], players,
                      treasure_deck=[f"t{i}" for i in range(5)],
                      combat=CombatState(fighter_ids=[101], monster_ids=monsters))
    state.card_decks = {cid: card.deck for cid, card in catalog.items()}
    return state, catalog


def test_tie_goes_to_monster():
    state, catalog = combat_game(monster_level=6)
    assert combat_strength(state, 101, catalog) == 6
    assert declare_result(state, 101, catalog).outcome == "must_run_away"


def test_strictly_greater_strength_wins_and_multiple_monsters_sum():
    state, catalog = combat_game(monster_level=5)
    assert declare_result(state, 101, catalog).outcome == "provisional_win"
    state.combat.monster_ids.append("m2")
    assert declare_result(state, 101, catalog).outcome == "must_run_away"


def test_helper_accepts_explicit_terms_and_adds_strength():
    state, catalog = combat_game(monster_level=7)
    state, _ = ask_help(state, 101, 102, 1, ["hat"], catalog)
    assert state.combat.pending_help == (102, 1, ["hat"])
    state, _ = accept_help(state, 102)
    assert state.combat.fighter_ids == [101, 102]
    assert declare_result(state, 101, catalog).outcome == "provisional_win"


def test_intervention_recalculates_declared_victory():
    state, catalog = combat_game(monster_level=5)
    state, _ = declare_win(state, 101, catalog, NOW)
    first_deadline = state.combat.reaction_deadline
    state, _ = play_combat_card(state, 103, "debuff", "m1", catalog, NOW + timedelta(seconds=5))
    assert state.combat.reaction_deadline is None
    assert declare_result(state, 101, catalog).outcome == "must_run_away"
    assert first_deadline is not None


def test_one_shot_from_hand_changes_fighter_strength_and_restarts_window():
    state, catalog = combat_game(monster_level=7)
    state.players[101].hand.append("buff")
    state, _ = play_combat_card(state, 101, "buff", "101", catalog, NOW)
    assert combat_strength(state, 101, catalog) == 9
    assert declare_result(state, 101, catalog).outcome == "provisional_win"
    assert "buff" in state.combat.played_card_ids
    assert "buff" not in state.treasure_discard


def test_rewards_wait_for_reaction_window_then_solo_draw_is_private():
    state, catalog = combat_game(monster_level=1)
    state, _ = declare_win(state, 101, catalog, NOW)
    with pytest.raises(RuleError, match="reaction window"):
        close_reaction(state, catalog, NOW + timedelta(seconds=1))
    assert state.players[101].level == 3
    state, events = close_reaction(state, catalog, NOW + timedelta(seconds=31))
    assert state.players[101].level == 4
    assert state.phase == "turn.charity"
    assert sum(e.name == "treasure.drawn" and e.audience == "user:101" for e in events) == 2
    assert all(e.name != "treasure.drawn" or e.audience != "group" for e in events)


def test_helped_treasure_is_public_and_promised_share_and_item_transfer():
    state, catalog = combat_game(monster_level=1)
    state, _ = ask_help(state, 101, 102, 1, ["hat"], catalog)
    state, _ = accept_help(state, 102)
    state, _ = declare_win(state, 101, catalog, NOW)
    state, events = close_reaction(state, catalog, NOW + timedelta(seconds=31))
    assert sum(e.name == "treasure.drawn" and e.audience == "group" for e in events) == 2
    assert len(state.players[102].hand) == 1
    assert len(state.players[101].hand) == 1
    assert "hat" in state.players[102].in_play
    assert "hat" not in state.players[101].in_play


def test_monster_kill_can_grant_tenth_level():
    state, catalog = combat_game(monster_level=1, player_level=9)
    state, _ = resolve_rewards(state, catalog)
    assert state.players[101].level == 10
    assert state.phase == "game.finished"


@pytest.mark.parametrize("die, escaped", [(4, False), (5, True)])
def test_escape_threshold_and_public_die_event(die, escaped):
    state, catalog = combat_game(monster_level=20)
    state, _ = begin_escape(state, 101, catalog)
    state, events = run_away(state, 101, "m1", FixedDie(die), catalog)
    roll = next(e for e in events if e.name == "escape.rolled")
    assert roll.data["die"] == die
    assert roll.data["escaped"] is escaped


def test_each_fighter_rolls_against_each_monster():
    state, catalog = combat_game(monster_level=20, second=True)
    state, _ = ask_help(state, 101, 102, 0, [], catalog)
    state, _ = accept_help(state, 102)
    state, _ = begin_escape(state, 101, catalog)
    rolls = []
    for user, monster in [(101, "m1"), (101, "m2"), (102, "m1"), (102, "m2")]:
        state, events = run_away(state, user, monster, FixedDie(5), catalog)
        rolls.extend(e for e in events if e.name == "escape.rolled")
    assert len(rolls) == 4
    assert state.phase == "turn.charity"


def test_helper_death_on_second_monster_does_not_erase_fighters_escape_rolls():
    state, catalog = combat_game(monster_level=20, second=True)
    from dataclasses import replace
    catalog = dict(catalog)
    catalog["m2"] = replace(catalog["m2"], bad_stuff=[{"op": "death"}])
    state, _ = ask_help(state, 101, 102, 0, [], catalog)
    state, _ = accept_help(state, 102)
    state, _ = begin_escape(state, 101, catalog)
    recorded = []
    for user, monster, die in [(101, "m1", 5), (101, "m2", 5),
                                (102, "m1", 5), (102, "m2", 4)]:
        state, events = run_away(state, user, monster, FixedDie(die), catalog)
        recorded.extend(e for e in events if e.name == "escape.rolled")
    assert len(recorded) == 4
    assert state.players[101].alive
    assert not state.players[102].alive
    assert state.phase == "turn.charity"


def test_bad_stuff_can_remove_item_and_death_creates_lootable_corpse():
    state, catalog = combat_game(monster_level=20)
    catalog = dict(catalog)
    from dataclasses import replace
    catalog["m1"] = replace(catalog["m1"], bad_stuff=[{"op": "remove_item", "card_id": "hat"}])
    state, _ = begin_escape(state, 101, catalog)
    state, _ = run_away(state, 101, "m1", FixedDie(4), catalog)
    assert "hat" not in state.players[101].in_play
    assert "hat" in state.treasure_discard

    state, catalog = combat_game(monster_level=20)
    catalog = dict(catalog)
    catalog["m1"] = replace(catalog["m1"], bad_stuff=[{"op": "death"}])
    state, _ = begin_escape(state, 101, catalog)
    state, _ = run_away(state, 101, "m1", FixedDie(4), catalog)
    assert not state.players[101].alive
    assert "role" in state.players[101].in_play
    assert "hat" in state.corpse[101]
    state, _ = loot_corpse(state, 102, 101, "hat")
    assert "hat" in state.players[102].in_play


def test_dead_player_returns_with_four_cards_from_each_deck_on_next_turn():
    state, catalog = combat_game(monster_level=20)
    from dataclasses import replace
    catalog = dict(catalog)
    catalog["m1"] = replace(catalog["m1"], bad_stuff=[{"op": "death"}])
    for i in range(4):
        cid = f"d{i}"
        catalog[cid] = CardDef(cid, "door", "special", cid)
        state.card_decks[cid] = "door"
    state.door_deck = [f"d{i}" for i in range(4)]
    state.treasure_deck = [f"t{i}" for i in range(5)]
    state, _ = begin_escape(state, 101, catalog)
    state, _ = run_away(state, 101, "m1", FixedDie(4), catalog)
    assert not state.players[101].alive
    state, _ = end_turn(state, 101, Random(1))
    state.phase = "turn.charity"
    state, _ = end_turn(state, 102, Random(1))
    state.phase = "turn.charity"
    state, _ = end_turn(state, 103, Random(1))
    assert state.active_user_id == 101
    assert state.players[101].alive
    assert len(state.players[101].hand) == 8


def test_looted_door_card_from_dead_hand_returns_to_looters_hand():
    state, catalog = combat_game(monster_level=20)
    from dataclasses import replace
    catalog = dict(catalog)
    catalog["m1"] = replace(catalog["m1"], bad_stuff=[{"op": "death"}])
    state.players[101].hand.append("debuff")
    state, _ = begin_escape(state, 101, catalog)
    state, _ = run_away(state, 101, "m1", FixedDie(4), catalog)
    state, _ = loot_corpse(state, 102, 101, "debuff")
    assert "debuff" in state.players[102].hand
    assert "debuff" not in state.players[102].in_play
