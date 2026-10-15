from copy import deepcopy
from datetime import timedelta
from random import Random

import pytest

from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command, CombatState, RuleError
from dota_dungeon.core.combat import loot_corpse
from dota_dungeon.core.loss_rules import death
from dota_dungeon.service.codec import decode_state, encode_state
from dota_dungeon.telegram.views import render_selection, render_view
from test_telegram_special import fixture
from test_service_router import NOW


def command(state, release, name, actor=11, **args):
    return decide(state, Command('g', actor, str(len(state.processed_requests)), name, {'now': NOW, **args}), release.catalog, Random(7))


@pytest.mark.parametrize('dead_level', [1, 2])
def test_charity_menu_excludes_dead_minimum_and_ties(dead_level):
    repo, router, ids = fixture('turn.charity')
    s = repo.games['g'].state
    s.players[11].level = 4
    s.players[22].alive = False
    s.players[22].level = dead_level
    s.players[33].level = 2
    s.players[11].hand = [c for c, d in router.release.catalog.items() if d.kind == 'monster'][:6]
    chosen = s.players[11].hand[0]
    view = render_selection(s, 11, 'charity', {'selected': [chosen]}, router.release, now=NOW)
    confirm = next(b for row in view.rows for b in row if b.action == 'give_charity')
    assert confirm.args == {'assignments': {33: [chosen]}}
    result, _ = command(s, router.release, confirm.action, **confirm.args)
    assert result.players[33].hand == [chosen]


def test_lowest_charity_uses_explicit_selection_and_rejects_bad_ids_atomically():
    repo, router, ids = fixture('turn.charity')
    s = repo.games['g'].state
    s.players[11].hand = [c for c, d in router.release.catalog.items() if d.kind == 'monster'][:6]
    chosen = s.players[11].hand[0]
    view = render_selection(s, 11, 'charity', {'selected': [chosen]}, router.release, now=NOW)
    confirm = next(b for row in view.rows for b in row if b.action == 'give_charity')
    assert confirm.args == {'assignments': {}, 'discard_ids': [chosen]}
    for bad in ([], [chosen, chosen], ['magic_missile:1']):
        rng = Random(7)
        before, random_before = deepcopy(s), rng.getstate()
        with pytest.raises(RuleError):
            decide(s, Command('g', 11, 'bad', 'give_charity', {'assignments': {}, 'discard_ids': bad}), router.release.catalog, rng)
        assert s == before and rng.getstate() == random_before
    result, events = command(s, router.release, confirm.action, **confirm.args)
    assert chosen in result.door_discard and chosen not in result.players[11].hand
    assert len(result.players[11].hand) == 5
    replay, ev = decide(result, Command('g',11,'0','give_charity',confirm.args), router.release.catalog, Random(7))
    assert replay == result and not ev


@pytest.mark.parametrize('from_hand', [True, False])
def test_all_corpse_loot_enters_hand_and_obeys_later_hand_limit(from_hand):
    repo, router, ids = fixture('turn.charity')
    s = repo.games['g'].state
    cid = 'mithril_armor:1'
    s.players[11].in_play = ['huge_rock:1']
    s.players[11].hand = [c for c, d in router.release.catalog.items() if d.kind == 'monster'][:5]
    s.players[22].alive = False
    s.corpse = {22: [cid]}
    s.corpse_hand = {22: {cid} if from_hand else set()}
    s.corpse_looted_by = {22: set()}
    s.corpse_loot_order = {22: [11]}
    result, events = loot_corpse(s,11,22,cid)
    assert result.players[11].hand.count(cid) == 1
    assert result.players[11].in_play == ['huge_rock:1'] and not result.corpse[22]
    assert events[0].audience == 'group' and events[0].data['card_id'] == cid
    with pytest.raises(RuleError, match='hand'):
        command(result,router.release,'end_turn')


def test_death_revives_next_turn_and_refills_once_on_own_turn_after_reload():
    repo, router, ids = fixture('turn.charity')
    s = repo.games['g'].state
    s.players[11].role_ids = ['warrior:1']
    s.players[11].in_play = ['warrior:1']
    s.door_deck = ['3_872_orcs:1','amazon:1','bigfoot:1','bullrog:1']
    s.treasure_deck = ['magic_missile:1','mithril_armor:1','huge_rock:1','pretty_balloons:1']
    s, _ = death(s,11,router.release.catalog,Random(1))
    assert not s.players[11].alive
    s, _ = command(s,router.release,'end_turn')
    assert s.active_user_id == 22 and s.players[11].alive and not s.players[11].hand
    assert s.players[11].rebirth_pending
    s = decode_state(encode_state(s))
    combat = deepcopy(s)
    combat.phase = 'combat.active'
    combat.combat = CombatState(fighter_ids=[22], monster_ids=['large_angry_chicken:1'])
    offered, _ = command(combat,router.release,'ask_help',actor=22,helper_id=11,treasure_count=0,item_ids=[])
    assert offered.combat.pending_help[0] == 11
    # A revived character can receive charity before their own replacement hand.
    s.phase = 'turn.charity'
    s.players[11].level = 1
    s.players[22].hand = [c for c,d in router.release.catalog.items() if d.kind == 'monster' and c not in s.door_deck][:6]
    gift = s.players[22].hand[0]
    s, _ = command(s,router.release,'give_charity',actor=22,assignments={11:[gift]})
    s.players[22].hand = []
    s, _ = command(s,router.release,'end_turn',actor=22)
    s.phase = 'turn.charity'
    s, _ = command(s,router.release,'end_turn',actor=33)
    assert s.active_user_id == 11 and len(s.players[11].hand) == 9
    assert gift in s.players[11].hand and not s.players[11].rebirth_pending
    assert s.players[11].role_ids == ['warrior:1']
    s = decode_state(encode_state(s))
    s.players[11].hand = []
    for actor in [11,22,33]:
        s.phase = 'turn.charity'
        s, _ = command(s,router.release,'end_turn',actor=actor)
    assert not s.players[11].hand

def test_visible_cards_inspectable_with_live_rewards_and_no_foreign_actions():
    repo, router, ids = fixture()
    s = repo.games['g'].state
    monster = 'plutonium_dragon:1'
    s.combat.monster_ids = [monster, 'mate:virtual']
    s.combat.virtual_monsters = {'mate:virtual': monster}
    s.combat.monster_modifiers = {monster: [{'amount': 5, 'treasures': 1, 'card_id':'ancient:1'}]}
    s.combat.modifier_ids = ['ancient:1']
    s.players[22].in_play = ['mithril_armor:1','elf:1']
    s.players[22].race_ids = ['elf:1']
    for cid in [monster, 'mate:virtual', 'mithril_armor:1', 'elf:1']:
        view = render_view(s,11,'card:'+cid,router.release,now=NOW)
        assert all(b.action == 'nav' for row in view.rows for b in row)
        assert router.release.presentations[monster if cid=='mate:virtual' else cid].description_ru in view.text
    view = render_view(s,11,'card:'+monster,router.release,now=NOW)
    assert '25' in view.text and '6' in view.text and 'Модификаторы' in view.text
    profile = render_view(s,11,'profile:22',router.release,now=NOW)
    assert any(b.args.get('screen')=='card:mithril_armor:1' for row in profile.rows for b in row)
    s.players[22].hand = ['magic_missile:1']
    for cid in ['magic_missile:1','potted_plant:1','mate:missing']:
        with pytest.raises(ValueError):
            render_view(s,11,'card:'+cid,router.release,now=NOW)
    with pytest.raises(ValueError):
        render_view(s,99,'card:'+monster,router.release,now=NOW)


def test_hand_curse_names_source_target_and_inspection_in_actual_router():
    from test_telegram_special import play_menu, click
    from test_service_router import button, press
    repo, router, ids = fixture('turn.prepare')
    cid = 'curse_lose_a_level:1'
    repo.games['g'].state.players[22].hand = [cid]
    play_menu(repo,router,22,cid)
    click(repo,router,22,'play_card',card_id=cid,target={'player_id':11})
    s = repo.get('g').state
    for viewer in [11,22,33]:
        view = render_view(s,viewer,'main',router.release,now=NOW)
        assert router.release.presentations[cid].display_name_ru in view.text
        assert '11' in view.text
    assert any(router.release.presentations[cid].display_name_ru in m['payload'].get('text','') and '11' in m['payload'].get('text','') for m in repo.outbox if m['payload'].get('chat_id')==-100)
    inspect = button(repo,'inspect_card',card_id=cid)
    before = deepcopy(repo.get('g'))
    for actor, chat in [(99,-100),(11,11)]:
        router.route_update(press(inspect,actor,len(repo.receipts)+100,chat=chat),now=NOW)
        assert repo.get('g').state == before.state and repo.get('g').version == before.version and repo.get('g').rng.getstate() == before.rng.getstate()
    router.route_update(press(inspect,11,len(repo.receipts)+100,chat=-100),now=NOW)
    assert repo.get('g').state == before.state and repo.get('g').version == before.version and repo.get('g').rng.getstate() == before.rng.getstate()
    assert any(router.release.presentations[cid].description_ru in m['payload'].get('text','') for m in repo.outbox if m['payload'].get('chat_id')==11)

@pytest.mark.parametrize('accepted', [False, True])
def test_promised_one_shot_cannot_be_voluntarily_consumed(accepted):
    repo, router, ids = fixture()
    s = repo.games['g'].state
    s.players[11].in_play = ['magic_missile:1']
    s, _ = command(s,router.release,'ask_help',helper_id=22,treasure_count=0,item_ids=['magic_missile:1'])
    if accepted:
        s, _ = command(s,router.release,'accept_help',actor=22)
    rng = Random(19)
    before, random_before = deepcopy(s), rng.getstate()
    with pytest.raises(RuleError,match='promised'):
        decide(s,Command('g',11,'consume','play_card',{'card_id':'magic_missile:1','target':{'player_id':11},'choices':{'side':'fighters'},'now':NOW}),router.release.catalog,rng)
    assert s == before and rng.getstate() == random_before


@pytest.mark.parametrize('accepted', [False, True])
def test_forced_promised_item_loss_is_disclosed_and_settles_after_reload(accepted):
    repo, router, ids = fixture()
    s = repo.games['g'].state
    s.players[11].in_play = ['mithril_armor:1','magic_missile:1']
    s.players[11].equipped = ['mithril_armor:1']
    s.players[33].hand = ['curse_lose_the_armor_you_are_wearing:1']
    s.treasure_deck = ['pretty_balloons:1','boots_of_butt_kicking:1']
    s, _ = command(s,router.release,'ask_help',helper_id=22,treasure_count=0,item_ids=['mithril_armor:1','magic_missile:1'])
    if accepted:
        s, _ = command(s,router.release,'accept_help',actor=22)
    s, _ = command(s,router.release,'play_card',actor=33,card_id='curse_lose_the_armor_you_are_wearing:1',target={'player_id':11})
    s, events = command(s,router.release,'respond_decision',decision_id=s.pending_decision.id,choices={})
    if s.pending_decision:
        assert 'mithril_armor:1' in s.pending_decision.payload['card_ids']
        s, ev = command(s,router.release,'respond_decision',decision_id=s.pending_decision.id,choices={'card_ids':['mithril_armor:1']})
        events += ev
    assert 'mithril_armor:1' in s.treasure_discard
    cancelled = [e for e in events if e.name == 'help.item_lost']
    assert {e.audience for e in cancelled} == {'group','user:22'}
    assert all(e.data['card_id']=='mithril_armor:1' for e in cancelled)
    if not accepted:
        assert s.combat.pending_help[2] == ['magic_missile:1']
        s, _ = command(s,router.release,'accept_help',actor=22)
    assert s.combat.help_item_ids == ['magic_missile:1']
    s = decode_state(encode_state(s))
    s, _ = command(s,router.release,'declare_win')
    s, events = command(s,router.release,'close_reaction',now=NOW+timedelta(seconds=61))
    assert s.combat is None
    assert s.players[22].in_play == ['magic_missile:1']
    assert s.treasure_discard.count('mithril_armor:1') == 1

def test_end_turn_waits_for_public_corpse_choices_before_reviving():
    repo, router, ids = fixture('turn.charity')
    s = repo.games['g'].state
    s.players[11].in_play = ['mithril_armor:1']
    s, _ = death(s,11,router.release.catalog,Random(1))
    with pytest.raises(RuleError,match='corpse'):
        command(s,router.release,'end_turn')
    looter = s.corpse_loot_order[11][0]
    s, _ = command(s,router.release,'loot_corpse',actor=looter,deceased_id=11,card_id='mithril_armor:1')
    s, _ = command(s,router.release,'end_turn')
    assert s.players[11].alive and s.players[11].rebirth_pending

def test_promised_item_cannot_pay_ability_and_forced_big_transfer_remains_selectable():
    repo, router, ids = fixture()
    s = repo.games['g'].state
    s.players[11].in_play = ['warrior:1','dwarf:1','magic_missile:1','huge_rock:1','mithril_armor:1']
    s.players[11].role_ids = ['warrior:1']
    s.players[11].race_ids = ['dwarf:1']
    s.players[33].hand = ['curse_lose_your_race:1']
    s.players[33].level = 1
    s, _ = command(s,router.release,'ask_help',helper_id=22,treasure_count=0,item_ids=['magic_missile:1','mithril_armor:1'])
    s, _ = command(s,router.release,'accept_help',actor=22)
    before = deepcopy(s)
    with pytest.raises(RuleError,match='promised'):
        command(s,router.release,'use_ability',ability_key='warrior_berserk',target={},cost_ids=['magic_missile:1'])
    assert s == before
    s, _ = command(s,router.release,'play_card',actor=33,card_id='curse_lose_your_race:1',target={'player_id':11})
    s, _ = command(s,router.release,'respond_decision',decision_id=s.pending_decision.id,choices={})
    assert s.players[11].pending_big_excess == 1
    s, ev = command(s,router.release,'resolve_big_items',card_ids=['mithril_armor:1'],recipient_id=33)
    assert 'mithril_armor:1' in s.players[33].in_play
    assert s.combat.help_item_ids == ['magic_missile:1']
    assert {e.audience for e in ev if e.name=='help.item_lost'} == {'group','user:22'}


def test_help_terms_are_visible_and_changed_offer_rejects_old_acceptance_callback():
    from test_telegram_special import play_menu, click
    from test_service_router import button, press
    from dota_dungeon.telegram.views import HELP_ITEM_TERMS
    repo, router, ids = fixture()
    s = repo.games['g'].state
    s.players[11].in_play = ['mithril_armor:1']
    s.players[11].equipped = ['mithril_armor:1']
    s.players[33].hand = ['curse_lose_the_armor_you_are_wearing:1']
    view = render_selection(s,11,'help',{'helper_id':22,'item_ids':['mithril_armor:1']},router.release,now=NOW)
    assert HELP_ITEM_TERMS in view.text
    s, ev = command(s,router.release,'ask_help',helper_id=22,treasure_count=0,item_ids=['mithril_armor:1'])
    repo.games['g'].state = s
    messages, callbacks = router._panel(repo.get('g'),22,'main',NOW)
    repo.enqueue('offer-panel',messages,callbacks=callbacks)
    assert HELP_ITEM_TERMS in render_view(s,22,'main',router.release,now=NOW).text
    old = button(repo,'accept_help',actor=22)
    play_menu(repo,router,33,'curse_lose_the_armor_you_are_wearing:1')
    click(repo,router,33,'play_card',card_id='curse_lose_the_armor_you_are_wearing:1',target={'player_id':11})
    click(repo,router,11,'select',flow='decision')
    click(repo,router,11,'respond_decision',choices={})
    assert repo.get('g').state.combat.pending_help[2] == []
    before = deepcopy(repo.get('g').state)
    router.route_update(press(old,22,len(repo.receipts)+100),now=NOW)
    assert repo.get('g').state == before and repo.get('g').state.combat.helper_id is None
    click(repo,router,22,'accept_help')
    assert repo.get('g').state.combat.helper_id == 22
