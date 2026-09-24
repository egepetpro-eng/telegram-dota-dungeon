import pytest

from dota_dungeon.core.effects import apply_effects
from dota_dungeon.core.model import GameState, Player, RuleError


def game(level):
    return GameState("g", -1, 101, "turn.prepare", 101, [101], {101: Player(101, level=level)})


def test_curse_never_reduces_below_level_one():
    state, _ = apply_effects(game(1), 101, [{"op": "lose_level", "amount": 2}], {})
    assert state.players[101].level == 1


def test_level_card_cannot_grant_winning_level():
    with pytest.raises(RuleError, match="winning level"):
        apply_effects(game(9), 101, [{"op": "gain_level", "amount": 1}], {})
