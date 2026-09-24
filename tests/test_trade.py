from datetime import datetime, timedelta, timezone

import pytest

from dota_dungeon.core.catalog import load_catalog
from dota_dungeon.core.model import CombatState, GameState, Player, RuleError
from dota_dungeon.core.trade import accept_trade, offer_trade


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def trade_game():
    catalog = load_catalog({"cards": [
        {"id": cid, "deck": "treasure", "kind": "item", "name": cid, "size": size}
        for cid, size in [("a", "small"), ("b", "small"), ("big-a", "big"), ("big-b", "big")]
    ]})
    state = GameState("g", -500, 101, "turn.prepare", 101, [101, 102],
                      {101: Player(101, hand=["b"], in_play=["a", "big-a"]),
                       102: Player(102, in_play=["big-b"])})
    return state, catalog


def offered(state, catalog, offered_ids=None, requested_ids=None):
    return offer_trade(state, 101, 102, offered_ids or ["a"], requested_ids or [],
                       NOW + timedelta(minutes=2), catalog, NOW)


def test_hand_card_cannot_be_traded():
    state, catalog = trade_game()
    with pytest.raises(RuleError, match="in play"):
        offered(state, catalog, ["b"])


def test_trade_transfers_both_sides_atomically_and_second_accept_fails():
    state, catalog = trade_game()
    state, _ = offered(state, catalog, ["a", "big-a"], ["big-b"])
    trade_id = next(iter(state.trades))
    state, _ = accept_trade(state, 102, trade_id, catalog, NOW)
    assert "a" in state.players[102].in_play
    assert "big-b" in state.players[101].in_play
    assert "a" not in state.players[101].in_play
    with pytest.raises(RuleError, match="no longer available"):
        accept_trade(state, 102, trade_id, catalog, NOW)


def test_trade_expires_and_keeps_ownership():
    state, catalog = trade_game()
    state, _ = offered(state, catalog)
    trade_id = next(iter(state.trades))
    with pytest.raises(RuleError, match="no longer available"):
        accept_trade(state, 102, trade_id, catalog, NOW + timedelta(minutes=3))
    assert "a" in state.players[101].in_play


def test_changed_ownership_prevents_accept():
    state, catalog = trade_game()
    state, _ = offered(state, catalog)
    trade_id = next(iter(state.trades))
    state.players[101].in_play.remove("a")
    with pytest.raises(RuleError, match="changed owner"):
        accept_trade(state, 102, trade_id, catalog, NOW)


def test_combat_blocks_trade():
    state, catalog = trade_game()
    state, _ = offered(state, catalog)
    state.combat = CombatState(fighter_ids=[101], monster_ids=["monster"])
    with pytest.raises(RuleError, match="combat"):
        accept_trade(state, 102, next(iter(state.trades)), catalog, NOW)


def test_trade_rejects_result_with_two_big_items():
    state, catalog = trade_game()
    state, _ = offered(state, catalog, ["big-a"])
    with pytest.raises(RuleError, match="Big"):
        accept_trade(state, 102, next(iter(state.trades)), catalog, NOW)
