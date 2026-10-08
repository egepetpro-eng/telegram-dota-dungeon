from copy import deepcopy
from random import Random

import pytest

from dota_dungeon.core.effects import apply_effects
from dota_dungeon.core.model import CardDef, GameState, Player, RuleError, Trade
from test_card_play import NOW


def fixture():
    catalog = {
        'head': CardDef('head', 'treasure', 'item', 'Head', slots='head'),
        'big': CardDef('big', 'treasure', 'item', 'Big', size='big'),
        'role': CardDef('role', 'door', 'role', 'Localized', rule_key='warrior'),
        'enabled': CardDef('enabled', 'treasure', 'item', 'Enabled', restrictions={'role_any': ['warrior']}),
        'secret': CardDef('secret', 'door', 'curse', 'Secret'),
    }
    state = GameState('g', -1, 1, 'turn.prepare', 1, [1, 2], {1: Player(1), 2: Player(2, hand=['secret'], in_play=['head', 'big', 'role', 'enabled'], equipped=['head', 'enabled'], role_ids=['role'])})
    state.card_decks = {cid: card.deck for cid, card in catalog.items()}
    return state, catalog


@pytest.mark.parametrize('selector,expected', [
    ({'zone': 'in_play', 'kind': 'item', 'slot': 'head'}, 'head'),
    ({'zone': 'in_play', 'kind': 'item', 'size': 'big'}, 'big'),
    ({'zone': 'in_play', 'kind': 'role'}, 'role'),
])
def test_select_open_card_and_discard(selector, expected):
    state, catalog = fixture()
    result, _ = apply_effects(state, 2, [{'op': 'remove_item', 'selector': selector}], catalog, rng=Random(3))
    assert expected not in result.players[2].in_play
    assert expected in result.door_discard + result.treasure_discard
    assert expected in state.players[2].in_play


def test_hand_loss_private_and_foreign_selection_rejected():
    state, catalog = fixture()
    effect = {'op': 'remove_item', 'selector': {'zone': 'hand'}}
    result, events = apply_effects(state, 2, [effect], catalog, rng=Random(3))
    assert result.players[2].hand == []
    assert any(e.audience == 'user:2' and 'secret' in str(e.data) for e in events)
    assert all('secret' not in str(e.data) for e in events if e.audience == 'group')
    with pytest.raises(RuleError):
        apply_effects(state, 2, [effect], catalog, choices={'card_id': 'head'})


def test_identity_loss_disables_equipment_and_cancels_trade():
    state, catalog = fixture()
    state.trades['t'] = Trade('t', 2, 1, ['head'], [], NOW)
    result, _ = apply_effects(state, 2, [{'op': 'remove_item', 'card_id': 'head'}, {'op': 'remove_item', 'selector': {'zone': 'in_play', 'kind': 'role'}}], catalog)
    assert result.trades['t'].status == 'cancelled'
    assert result.players[2].role_ids == []
    assert result.players[2].equipped == []
    assert 'enabled' in result.players[2].in_play


def test_no_eligible_selector_and_bad_final_operand_are_atomic():
    state, catalog = fixture()
    before = deepcopy(state)
    with pytest.raises(RuleError):
        apply_effects(state, 2, [{'op': 'lose_level'}, {'op': 'remove_item', 'selector': {'zone': 'in_play', 'kind': 'race'}}], catalog)
    assert state == before
    with pytest.raises(RuleError):
        apply_effects(state, 2, [{'op': 'lose_level'}, {'op': 'remove_item', 'card_id': 'foreign'}], catalog)
    assert state == before


def test_stable_rule_key_and_tag_selectors_ignore_display_names():
    from dataclasses import replace
    state, catalog = fixture()
    catalog['big'] = replace(catalog['big'], tags=('synthetic-mark',))
    result, _ = apply_effects(state, 2, [{'op': 'remove_item', 'selector': {'zone': 'in_play', 'rule_key': 'warrior'}}], catalog)
    assert result.players[2].role_ids == []
    result, _ = apply_effects(state, 2, [{'op': 'remove_item', 'selector': {'zone': 'in_play', 'tag': 'synthetic-mark'}}], catalog)
    assert result.treasure_discard == ['big']


def test_failed_chain_does_not_advance_random_source():
    state, catalog = fixture()
    rng = Random(3)
    before_rng = rng.getstate()
    state.players[2].level = 9
    before = deepcopy(state)
    with pytest.raises(RuleError):
        apply_effects(state, 2, [{'op': 'remove_item', 'selector': {'zone': 'hand'}}, {'op': 'gain_level'}], catalog, rng=rng)
    assert state == before
    assert rng.getstate() == before_rng
