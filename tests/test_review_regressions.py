from datetime import datetime, timedelta, timezone
from random import Random

import pytest

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.combat import (
    accept_help, ask_help, close_reaction, declare_win, play_combat_card,
)
from dota_dungeon.core.effects import apply_effects
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import CardDef, CombatState, Command, GameState, Player, RuleError
from dota_dungeon.core.trade import accept_trade, offer_trade
from dota_dungeon.core.turn import open_door


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def cards():
    return load_catalog({"cards": [
        {"id": "m", "deck": "door", "kind": "monster", "name": "Creep", "bonus": 1, "treasures": 1},
        {"id": "role", "deck": "door", "kind": "role", "name": "Hero", "bonus": 2},
        {"id": "race", "deck": "door", "kind": "race", "name": "Origin", "bonus": 1},
        {"id": "mod", "deck": "door", "kind": "modifier", "name": "Weak buff", "bonus": 1},
        {"id": "item", "deck": "treasure", "kind": "item", "name": "Sword", "value": 100},
        {"id": "prize", "deck": "treasure", "kind": "item", "name": "Prize", "value": 100},
    ]})


def state(phase="turn.prepare", level=3):
    players = {101: Player(101, level=level), 102: Player(102)}
    result = GameState("g", -500, 101, phase, 101, [101, 102], players,
                       door_deck=["m", "mod", "race", "role"], treasure_deck=["prize", "item"])
    result.card_decks = {cid: card.deck for cid, card in cards().items()}
    return result


def test_solo_reward_is_addressed_to_fighter_not_command_actor():
    catalog = cards()
    game = state("combat.active")
    game.door_deck.remove("m")
    game.combat = CombatState(fighter_ids=[101], monster_ids=["m"])
    game, _ = declare_win(game, 101, catalog, NOW)
    with pytest.raises(RuleError, match="not your turn"):
        decide(game, Command("g", 102, "bad-close", "close_reaction", {"now": NOW + timedelta(seconds=31)}), catalog, Random(1))
    game, events = close_reaction(game, catalog, NOW + timedelta(seconds=31))
    drawn = next(event for event in events if event.name == "treasure.drawn")
    assert drawn.audience == "user:101"


def test_persistent_effect_moves_card_out_of_hand():
    game = state()
    game.door_deck.remove("role")
    game.players[101].hand.append("role")
    game, _ = apply_effects(game, 101, [{"op": "persistent", "card_id": "role"}], cards())
    assert "role" in game.players[101].in_play
    assert "role" not in game.players[101].hand


def test_role_and_race_can_be_played_from_hand_through_engine():
    catalog = cards()
    game = state()
    for cid in ("role", "race"):
        game.door_deck.remove(cid)
        game.players[101].hand.append(cid)
        game, events = decide(game, Command("g", 101, cid, "play_identity", {"card_id": cid}), catalog, Random(1))
        assert any(event.audience == "group" and event.name == "identity.played" for event in events)
    assert game.players[101].role_ids == ["role"]
    assert game.players[101].race_ids == ["race"]
    assert set(game.players[101].in_play) == {"role", "race"}


def test_help_cannot_promise_more_treasures_than_monster_drops():
    catalog = cards()
    game = state("combat.active")
    game.door_deck.remove("m")
    game.combat = CombatState(fighter_ids=[101], monster_ids=["m"])
    with pytest.raises(RuleError, match="promised treasure"):
        ask_help(game, 101, 102, 2, [], catalog)


def test_intervention_that_leaves_fighter_ahead_restarts_deadline():
    catalog = cards()
    game = state("combat.active")
    game.door_deck.remove("m")
    game.door_deck.remove("mod")
    game.players[102].hand.append("mod")
    game.combat = CombatState(fighter_ids=[101], monster_ids=["m"])
    game, _ = declare_win(game, 101, catalog, NOW)
    game, events = play_combat_card(game, 102, "mod", "m", catalog, NOW + timedelta(seconds=5))
    assert game.combat.reaction_deadline == NOW + timedelta(seconds=35)
    assert any(event.name == "combat.reaction_restarted" for event in events)


def test_trade_rejects_role_card_and_expiry_longer_than_two_minutes():
    catalog = cards()
    game = state()
    game.door_deck.remove("role")
    game.players[101].in_play.append("role")
    with pytest.raises(RuleError, match="item"):
        offer_trade(game, 101, 102, ["role"], [], NOW + timedelta(minutes=1), catalog, NOW)
    game.door_deck.remove("race")
    game.players[101].in_play.remove("role")
    game.door_deck.append("role")
    game.treasure_deck.remove("item")
    game.players[101].in_play.append("item")
    with pytest.raises(RuleError, match="two minutes"):
        offer_trade(game, 101, 102, ["item"], [], NOW + timedelta(minutes=3), catalog, NOW)


def test_opening_combat_cancels_pending_trade():
    catalog = cards()
    game = state()
    game.treasure_deck.remove("item")
    game.players[101].in_play.append("item")
    game, _ = offer_trade(game, 101, 102, ["item"], [], NOW + timedelta(minutes=2), catalog, NOW)
    trade_id = next(iter(game.trades))
    game.door_deck.remove("m")
    game.door_deck.append("m")
    game, _ = open_door(game, 101, catalog)
    assert game.trades[trade_id].status == "cancelled"
    with pytest.raises(RuleError, match="no longer available"):
        accept_trade(game, 102, trade_id, catalog, NOW + timedelta(seconds=5))


def test_negative_level_effect_is_rejected_by_catalog_and_runtime():
    with pytest.raises(ValueError, match="positive amount"):
        load_catalog({"cards": [{"id": "curse", "deck": "door", "kind": "curse", "name": "Bad",
                                "effects": [{"op": "lose_level", "amount": -9}]}]})
    with pytest.raises(RuleError, match="positive amount"):
        apply_effects(state(level=1), 101, [{"op": "lose_level", "amount": -9}], cards())
