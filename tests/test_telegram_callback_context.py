"""All delivered callbacks validate Telegram destination type before dispatch."""
from copy import deepcopy

import pytest

from test_service_router import NOW, button, message, press
from test_telegram_special import fixture, play_menu, click


def reject_chat_types(repo, router, intent, actor, invalid_types):
    before = repo.get('g')
    intentions = deepcopy(repo.intents)
    for chat_type in invalid_types:
        update = press(intent, actor, len(repo.receipts) + 1000)
        chat = update['callback_query']['message']['chat']
        if chat_type is None:
            chat.pop('type')
        else:
            chat['type'] = chat_type
        sent = len(repo.outbox)
        router.route_update(update, now=NOW)
        actual = repo.get('g')
        assert actual.state == before.state
        assert actual.rng.getstate() == before.rng.getstate()
        assert (actual.version, actual.metadata, actual.status) == (
            before.version, before.metadata, before.status
        )
        assert repo.intents == intentions
        assert len(repo.outbox) == sent + 1
        assert repo.outbox[-1]['method'] == 'answerCallbackQuery'
        assert repo.outbox[-1]['payload']['show_alert'] is True


def test_private_decision_rejects_mismatched_unsupported_missing_type_then_validates():
    repo, router, ids = fixture('turn.prepare')
    curse = ids['curse_lose_a_level'][0]
    repo.games['g'].state.players[22].hand = [curse]
    play_menu(repo, router, 22, curse)
    click(repo, router, 22, 'play_card', card_id=curse, target={'player_id': 11})
    click(repo, router, 11, 'select', flow='decision')
    intent = button(repo, 'respond_decision', actor=11, choices={})
    reject_chat_types(repo, router, intent, 11, ['group', 'supergroup', 'channel', None])
    click(repo, router, 11, 'respond_decision', choices={})
    assert repo.get('g').state.players[11].level == 4
    assert repo.get('g').state.pending_decision is None


def test_private_navigation_and_selector_do_not_deliver_data_under_wrong_type():
    repo, router, ids = fixture('turn.prepare')
    curse = ids['curse_lose_a_level'][0]
    repo.games['g'].state.players[22].hand = [curse]
    play_menu(repo, router, 22, curse)
    click(repo, router, 22, 'play_card', card_id=curse, target={'player_id': 11})
    for action, args in [('nav', {'screen': 'hand'}), ('select', {'flow': 'decision'})]:
        intent = button(repo, action, actor=11, **args)
        reject_chat_types(repo, router, intent, 11, ['supergroup', None])
        click(repo, router, 11, action, **args)
        assert repo.outbox[-1]['payload']['chat_id'] == 11
        assert repo.outbox[-1]['method'] == 'sendMessage'


@pytest.mark.parametrize('valid_type', ['group', 'supergroup'])
def test_group_gameplay_rejects_private_missing_channel_type_and_accepts_group_types(valid_type):
    repo, router, _ = fixture()
    router.route_update(message(11, -100, '/game', 100), now=NOW)
    intent = button(repo, 'declare_win', actor=11)
    reject_chat_types(repo, router, intent, 11, ['private', 'channel', None])
    update = press(intent, 11, len(repo.receipts) + 1000)
    update['callback_query']['message']['chat']['type'] = valid_type
    router.route_update(update, now=NOW)
    assert repo.get('g').state.combat.reaction_deadline is not None
    assert repo.get('g').version == 1


def test_host_pause_and_end_confirmation_use_the_shared_context_check():
    repo, router, _ = fixture()
    router.route_update(message(11, -100, '/game', 100), now=NOW)
    reject_chat_types(repo, router, button(repo, 'pause', actor=11), 11,
                      ['private', 'channel', None])
    click(repo, router, 11, 'pause')
    assert repo.get('g').status == 'paused'
    router.route_update(message(11, -100, '/endgame', len(repo.receipts) + 1000), now=NOW)
    intent = button(repo, 'confirm_endgame', actor=11)
    reject_chat_types(repo, router, intent, 11, ['private', 'channel', None])
    click(repo, router, 11, 'confirm_endgame')
    assert repo.get('g').status == 'finished'
