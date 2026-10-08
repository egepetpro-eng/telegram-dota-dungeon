from copy import deepcopy
from datetime import datetime, timezone, timedelta
from random import Random

import pytest

from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import CardDef, CombatState, Command, GameState, Player, RuleError, Trade

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def fixture(kind='level_up', effects=None, target_rule='self', phase='turn.prepare'):
    card = CardDef('played', 'door' if kind == 'curse' else 'treasure', kind, 'Synthetic',
                   effects=effects if effects is not None else [{'op': 'gain_level'}],
                   play_phases=(phase,), target_rule=target_rule)
    state = GameState('g', -1, 1, phase, 1, [1, 2], {1: Player(1, level=8, hand=['played']), 2: Player(2, level=4)})
    state.card_decks = {'played': card.deck}
    return state, {'played': card}


def play(state, catalog, target=None, actor=1, request='r'):
    return decide(state, Command('g', actor, request, 'play_card', {'card_id': 'played', 'target': target or {}, 'now': NOW}), catalog, Random(3))


def zones(state):
    cards = state.door_deck + state.treasure_deck + state.door_discard + state.treasure_discard
    cards += [cid for p in state.players.values() for cid in p.hand + p.in_play]
    if state.combat:
        cards += state.combat.monster_ids + state.combat.played_card_ids
    return cards


def test_normal_level_card_and_replay_consume_once():
    state, catalog = fixture()
    result, events = play(state, catalog)
    assert result.players[1].level == 9
    assert result.treasure_discard == ['played']
    assert state.players[1].hand == ['played']
    replay, repeated = play(result, catalog)
    assert replay is result and repeated == []


def test_level_nine_rejected_retains_card():
    state, catalog = fixture()
    state.players[1].level = 9
    before = deepcopy(state)
    with pytest.raises(RuleError, match='winning level'):
        play(state, catalog)
    assert state == before


def test_curse_target_another_player_discard_actual_deck():
    state, catalog = fixture('curse', [{'op': 'lose_level'}], 'player')
    result, _ = play(state, catalog, {'player_id': 2})
    assert result.players[2].level == 3
    assert result.players[1].level == 8
    assert result.door_discard == ['played']


@pytest.mark.parametrize('target,phase', [({'player_id': 999}, 'turn.prepare'), ({}, 'lobby'), ({'card_id': 'secret'}, 'turn.prepare')])
def test_invalid_target_or_phase_preserves_input(target, phase):
    state, catalog = fixture()
    state.phase = phase
    before = deepcopy(state)
    with pytest.raises(RuleError):
        play(state, catalog, target)
    assert state == before


def test_carried_item_has_no_bonus():
    state, catalog = fixture('item', [])
    result, _ = play(state, catalog)
    assert result.players[1].in_play == ['played']
    assert result.players[1].equipped == []
    assert zones(result) == ['played']


def test_last_chained_effect_failure_is_atomic():
    state, catalog = fixture('one_shot', [{'op': 'draw', 'amount': 2}, {'op': 'gain_level'}])
    state.players[1].level = 9
    catalog['drawn'] = CardDef('drawn', 'treasure', 'item', 'Drawn')
    state.card_decks['drawn'] = 'treasure'
    state.treasure_deck = ['drawn']
    before = deepcopy(state)
    with pytest.raises(RuleError):
        play(state, catalog)
    assert state == before


@pytest.mark.parametrize('source', ['hand', 'in_play'])
def test_combat_one_shot_retained_until_victory(source):
    from dota_dungeon.core.combat import declare_win, close_reaction
    state, catalog = fixture('one_shot', [{'op': 'add_strength', 'amount': 2}], phase='combat.active')
    if source == 'in_play':
        state.players[1].hand = []
        state.players[1].in_play = ['played']
    catalog['monster'] = CardDef('monster', 'door', 'monster', 'Synthetic monster', bonus=1)
    state.card_decks['monster'] = 'door'
    state.combat = CombatState(fighter_ids=[1], monster_ids=['monster'])
    result, _ = play(state, catalog)
    assert result.combat.played_card_ids == ['played']
    assert result.treasure_discard == []
    assert set(zones(result)) == {'played', 'monster'}
    assert len(zones(result)) == 2
    result, _ = declare_win(result, 1, catalog, NOW)
    result, _ = close_reaction(result, catalog, NOW + timedelta(seconds=31))
    assert result.combat is None
    assert result.treasure_discard == ['played']
    assert result.door_discard == ['monster']
    assert len(zones(result)) == 2


def test_combat_modifier_retention_and_escape_cleanup():
    from dota_dungeon.core.combat import play_combat_card, begin_escape, run_away
    state, catalog = fixture('modifier', [], 'monster', 'combat.active')
    catalog['monster'] = CardDef('monster', 'door', 'monster', 'Synthetic monster', bonus=30)
    state.card_decks['monster'] = 'door'
    state.combat = CombatState(fighter_ids=[1], monster_ids=['monster'])
    result, _ = play_combat_card(state, 1, 'played', 'monster', catalog, NOW)
    assert result.combat.modifier_ids == result.combat.played_card_ids == ['played']
    result, _ = begin_escape(result, 1, catalog)
    result, _ = run_away(result, 1, 'monster', Random(5), catalog)
    assert result.combat is None
    assert result.treasure_discard == ['played']
    assert len(zones(result)) == 2


def test_cost_exact_and_all_hand_validation():
    from dota_dungeon.core.play import validate_cost
    player = Player(1, hand=['a', 'b', 'c', 'd'])
    validate_cost(player, {'zone': 'hand', 'count': 3, 'mode': 'all_hand'}, ['a', 'b', 'c', 'd'])
    for chosen in (['a', 'b', 'c'], ['a', 'b', 'c', 'foreign'], ['a', 'a', 'b', 'c']):
        with pytest.raises(RuleError):
            validate_cost(player, {'zone': 'hand', 'count': 3, 'mode': 'all_hand'}, chosen)
    with pytest.raises(RuleError):
        validate_cost(player, {'zone': 'hand', 'count': 5}, ['a', 'b', 'c', 'd'])
    assert player.hand == ['a', 'b', 'c', 'd']


def test_nonactive_initial_equipment_and_identity():
    state, catalog = fixture('role', [])
    state.players[1].hand = []
    state.players[2].hand = ['played']
    result, _ = play(state, catalog, actor=2)
    assert result.players[2].role_ids == ['played']
    state, catalog = fixture('item', [])
    state.players[1].hand = []
    state.players[2].hand = ['played']
    result, _ = decide(state, Command('g', 2, 'equip', 'equip', {'card_id': 'played'}), catalog, Random(3))
    assert result.players[2].equipped == ['played']

@pytest.mark.parametrize('name,args,actor', [('leave_lobby', {}, 2), ('decline_help', {}, 2), ('cancel_trade', {'trade_id': 't'}, 1)])
def test_lifecycle_commands_authorized_and_replay_safe(name, args, actor):
    state, catalog = fixture()
    if name == 'leave_lobby':
        state.phase = 'lobby'
        state.players[2].ready = True
    elif name == 'decline_help':
        state.phase = 'combat.active'
        state.combat = CombatState(fighter_ids=[1], pending_help=(2, 0, []))
    else:
        state.trades['t'] = Trade('t', 1, 2, [], [], NOW + timedelta(minutes=1))
    command = Command('g', actor, 'lifecycle', name, args)
    result, _ = decide(state, command, catalog, Random(3))
    if name == 'leave_lobby':
        assert 2 not in result.players and result.order == [1]
    elif name == 'decline_help':
        assert result.combat.pending_help is None
    else:
        assert result.trades['t'].status == 'cancelled'
    replay, events = decide(result, command, catalog, Random(3))
    assert replay is result and events == []


@pytest.mark.parametrize('name,args,actor', [('leave_lobby', {}, 2), ('decline_help', {}, 1), ('cancel_trade', {'trade_id': 't'}, 3)])
def test_lifecycle_rejects_invalid_actor_or_phase_atomically(name, args, actor):
    state, catalog = fixture()
    state.trades['t'] = Trade('t', 1, 2, [], [], NOW)
    state.combat = CombatState(fighter_ids=[1], pending_help=(2, 0, [])) if name == 'decline_help' else None
    state.phase = 'combat.active' if name == 'decline_help' else 'turn.prepare'
    before = deepcopy(state)
    with pytest.raises(RuleError):
        decide(state, Command('g', actor, 'lifecycle', name, args), catalog, Random(3))
    assert state == before


def test_persistent_played_card_stays_open_and_does_not_discard():
    state, catalog = fixture('curse', [{'op': 'persistent'}], 'player')
    result, _ = play(state, catalog, {'player_id': 2})
    assert result.players[1].hand == []
    assert result.players[2].in_play == ['played']
    assert result.door_discard == []
    assert zones(result) == ['played']


def test_restricted_item_cannot_be_equipped_without_identity():
    state, catalog = fixture('item', [])
    from dataclasses import replace
    catalog['played'] = replace(catalog['played'], restrictions={'role_any': ['warrior']})
    before = deepcopy(state)
    with pytest.raises(RuleError):
        decide(state, Command('g', 1, 'equip', 'equip', {'card_id': 'played'}), catalog, Random(3))
    assert state == before


def test_nonactive_equipment_outside_initial_preparation_rejected():
    state, catalog = fixture('item', [])
    state.turn_number = 3
    state.players[1].hand = []
    state.players[2].hand = ['played']
    before = deepcopy(state)
    with pytest.raises(RuleError):
        decide(state, Command('g', 2, 'equip', 'equip', {'card_id': 'played'}), catalog, Random(3))
    assert state == before


def test_host_cannot_leave_and_cancel_trade_forbidden_during_combat():
    state, catalog = fixture()
    state.phase = 'lobby'
    before = deepcopy(state)
    with pytest.raises(RuleError):
        decide(state, Command('g', 1, 'leave', 'leave_lobby'), catalog, Random(3))
    assert state == before
    state.phase = 'combat.active'
    state.combat = CombatState(fighter_ids=[1])
    state.trades['t'] = Trade('t', 1, 2, [], [], NOW)
    before = deepcopy(state)
    with pytest.raises(RuleError):
        decide(state, Command('g', 2, 'cancel', 'cancel_trade', {'trade_id': 't'}), catalog, Random(3))
    assert state == before


def test_curse_without_eligible_target_retains_all_zones():
    state, catalog = fixture('curse', [{'op': 'remove_item', 'selector': {'zone': 'in_play', 'kind': 'item'}}], 'player')
    before = deepcopy(state)
    with pytest.raises(RuleError, match='no eligible target'):
        play(state, catalog, {'player_id': 2})
    assert state == before


def test_combat_target_operand_is_resolved_server_side():
    state, catalog = fixture('one_shot', [{'op': 'prevent_bad_stuff', 'monster_id': '$target'}], 'combat', 'combat.active')
    catalog['monster'] = CardDef('monster', 'door', 'monster', 'Synthetic monster')
    state.combat = CombatState(fighter_ids=[1], monster_ids=['monster'])
    result, _ = play(state, catalog, {'player_id': 1, 'monster_id': 'monster'})
    assert result.combat.prevented_bad_stuff == {(1, 'monster')}
    before = deepcopy(state)
    with pytest.raises(RuleError):
        play(state, catalog, {'player_id': 1, 'monster_id': 'foreign'})
    assert state == before


def test_play_card_cannot_target_another_hidden_hand_by_card_id():
    state, catalog = fixture('curse', [{'op': 'remove_item', 'selector': {'zone': 'hand'}}], 'player')
    state.players[2].hand = ['secret']
    before = deepcopy(state)
    with pytest.raises(RuleError):
        play(state, catalog, {'player_id': 2, 'card_id': 'secret'})
    assert state == before


def test_declared_empty_phases_are_not_bypassed_by_legacy_combat_command():
    from dota_dungeon.core.combat import play_combat_card
    state, catalog = fixture('one_shot', [{'op': 'add_strength'}], 'player', 'combat.active')
    from dataclasses import replace
    catalog['played'] = replace(catalog['played'], rule_key='synthetic-no-play', play_phases=())
    state.combat = CombatState(fighter_ids=[1], monster_ids=[])
    before = deepcopy(state)
    with pytest.raises(RuleError):
        play_combat_card(state, 1, 'played', '1', catalog, NOW)
    assert state == before


def test_self_hand_loss_excludes_the_played_source_and_preserves_rng_on_rejection():
    state, catalog = fixture('curse', [{'op': 'remove_item', 'selector': {'zone': 'hand'}}])
    before = deepcopy(state)
    rng = Random(3)
    rng_before = rng.getstate()
    command = Command('g', 1, 'source-reservation', 'play_card', {'card_id': 'played', 'target': {}, 'now': NOW})
    with pytest.raises(RuleError):
        decide(state, command, catalog, rng)
    assert state == before
    assert rng.getstate() == rng_before


def test_self_hand_loss_consumes_another_card_and_source_exactly_once():
    state, catalog = fixture('curse', [{'op': 'remove_item', 'selector': {'zone': 'hand'}}])
    catalog['other'] = CardDef('other', 'treasure', 'item', 'Synthetic other')
    state.players[1].hand.append('other')
    state.card_decks['other'] = 'treasure'
    result, _ = play(state, catalog)
    assert result.players[1].hand == []
    assert result.door_discard == ['played']
    assert result.treasure_discard == ['other']
    assert sorted(zones(result)) == ['other', 'played']


def test_reaction_finalization_failure_preserves_input_and_supplied_rng():
    state, catalog = fixture('curse', [{'op': 'remove_item', 'selector': {'zone': 'hand'}}], 'player', 'combat.active')
    catalog['monster'] = CardDef('monster', 'door', 'monster', 'Synthetic monster', bonus=1)
    catalog['other'] = CardDef('other', 'treasure', 'item', 'Synthetic other')
    state.players[2].hand = ['other']
    state.card_decks.update({'monster': 'door', 'other': 'treasure'})
    state.combat = CombatState(fighter_ids=[1], monster_ids=['monster'], reaction_deadline=NOW)
    before = deepcopy(state)
    rng = Random(3)
    rng_before = rng.getstate()
    command = Command('g', 1, 'late-failure', 'play_card', {'card_id': 'played', 'target': {'player_id': 2}, 'now': datetime.max})
    # All effects succeed; restarting the reaction overflows the supplied time.
    with pytest.raises(OverflowError):
        decide(state, command, catalog, rng)
    assert state == before
    assert rng.getstate() == rng_before


@pytest.mark.parametrize('phase,turn_number,allowed', [('turn.prepare', 1, True), ('turn.prepare', 3, False), ('turn.after_door', 1, False)])
def test_generic_item_carrying_obeys_initial_preparation_boundary(phase, turn_number, allowed):
    state, catalog = fixture('item', [], phase=phase)
    state.turn_number = turn_number
    state.players[1].hand = []
    state.players[2].hand = ['played']
    before = deepcopy(state)
    if allowed:
        result, _ = play(state, catalog, actor=2)
        assert result.players[2].in_play == ['played']
        assert state == before
    else:
        with pytest.raises(RuleError, match='not your turn'):
            play(state, catalog, actor=2)
        assert state == before
