from copy import deepcopy
from datetime import timedelta
from random import Random
import pytest
from dota_dungeon.cards.installed import validate_installed_release
from dota_dungeon.core.model import GameState, Player, CombatState
from dota_dungeon.core import combat
from dota_dungeon.telegram.router import Router
from dota_dungeon.telegram.views import render_view
from test_service_router import MemoryRepository, NOW, button, message, press


def fixture(phase='combat.active'):
    release = validate_installed_release()
    ids = {}
    for cid, card in release.catalog.items():
        ids.setdefault(card.rule_key, []).append(cid)
    state = GameState('g', -100, 11, phase, 11, [11,22,33], {u: Player(u, level=5) for u in (11,22,33)}, card_decks={cid:c.deck for cid,c in release.catalog.items()})
    state.catalog_version, state.catalog_digest = release.version, release.digest
    if phase.startswith('combat'):
        state.combat = CombatState(fighter_ids=[11], monster_ids=[ids['lame_goblin'][0]])
    repo = MemoryRepository()
    repo.create(state, Random(1), {'reaction_seconds':60})
    for u in state.order: repo.link_private(u,u)
    return repo, Router(repo, release, 'bot'), ids


def click(repo, router, actor, action, **args):
    choice = button(repo, action, actor=actor, **args)
    router.route_update(press(choice, actor, len(repo.receipts)+100), now=NOW)
    return choice


def play_menu(repo, router, actor, cid):
    router.route_update(message(actor, actor, '/hand', len(repo.receipts)+100), now=NOW)
    click(repo, router, actor, 'nav', screen='card:'+cid)
    click(repo, router, actor, 'choose_card_target', card_id=cid)


def test_real_wandering_then_mate_virtual_target_and_trusted_reaction():
    repo, router, ids = fixture()
    wander, enemy, mate = (ids[k][0] for k in ('wandering_monster','potted_plant','mate'))
    repo.games['g'].state.players[22].hand = [wander, enemy, mate]
    before = deepcopy(repo.games['g'])
    play_menu(repo, router, 22, wander)
    assert repo.get('g').state == before.state and repo.get('g').rng.getstate() == before.rng.getstate()
    click(repo, router, 22, 'play_card', card_id=wander, choices={'monster_card_id':enemy})
    s = repo.get('g').state
    assert enemy in s.combat.monster_ids and not {wander,enemy}&set(s.players[22].hand)
    assert s.combat.reaction_seconds == 60
    play_menu(repo, router, 22, mate)
    click(repo, router, 22, 'play_card', card_id=mate, target={'monster_id':enemy})
    s = repo.get('g').state
    assert len(s.combat.virtual_monsters) == 1
    assert render_view(s,11,'group',router.release,now=NOW).text


def test_curse_victim_private_loss_real_delivered_path_and_authorization():
    repo, router, ids = fixture('turn.prepare')
    curse, item = ids['curse_lose_a_small_item'][0],ids['pretty_balloons'][0]
    repo.games['g'].state.players[22].hand = [curse]
    repo.games['g'].state.players[11].hand = [item]
    play_menu(repo,router,22,curse)
    click(repo,router,22,'play_card',card_id=curse,target={'player_id':11})
    click(repo,router,11,'select',flow='decision')
    click(repo,router,11,'respond_decision',choices={})
    assert repo.get('g').state.pending_decision.kind == 'loss_choice'
    assert item not in str(render_view(repo.get('g').state,22,'main',router.release,now=NOW).rows)
    click(repo,router,11,'select',flow='decision')
    click(repo,router,11,'select',flow='decision',selected=[item])
    choose = button(repo,'respond_decision',actor=11,choices={'card_ids':[item]})
    before = deepcopy(repo.get('g'))
    for user,chat,when in [(22,11,NOW),(11,-999,NOW),(11,11,NOW+timedelta(seconds=121))]:
        router.route_update(press(choose,user,len(repo.receipts)+100,chat=chat),now=when)
        assert repo.get('g').state == before.state and repo.get('g').rng.getstate()==before.rng.getstate()
    click(repo,router,11,'respond_decision',choices={'card_ids':[item]})
    assert item in repo.get('g').state.treasure_discard and not repo.get('g').state.pending_decision


def test_own_loaded_die_from_real_bad_stuff_then_continue():
    repo,router,ids=fixture()
    s=repo.games['g'].state
    die=ids['loaded_die'][0]
    s.players[11].hand=[die]
    s.players[11].level=8
    orcs=ids['3_872_orcs'][0]
    s.combat.monster_ids=[orcs]
    s,_=combat.apply_bad_stuff(s,11,orcs,router.release.catalog,rng=Random(1),now=NOW)
    repo.games['g'].state=s
    play_menu(repo,router,11,die)
    roll=s.pending_decision.id
    assert len([c for c in repo.intents.values() if c.action=='play_card' and c.args.get('card_id')==die])==6
    click(repo,router,11,'play_card',card_id=die,choices={'roll_id':roll,'result':6})
    click(repo,router,11,'select',flow='decision')
    click(repo,router,11,'respond_decision',choices={})
    assert repo.get('g').state.players[11].alive
    assert repo.get('g').state.players[11].level==2


def test_public_corpse_card_selector_uses_current_looter():
    repo,router,ids=fixture()
    s=repo.games['g'].state
    item=ids['pretty_balloons'][0]
    s.players[11].hand=[item]
    s.players[22].level=6
    s.players[33].level=4
    s.combat.monster_ids=[ids['bullrog'][0]]
    s,_=combat.apply_bad_stuff(s,11,ids['bullrog'][0],router.release.catalog,rng=Random(1),now=NOW)
    repo.games['g'].state=s
    view=render_view(s,22,'corpses',router.release,now=NOW)
    assert any(b.action=='loot_corpse' and b.args['card_id']==item for row in view.rows for b in row)
    router.route_update(message(22,22,'/game',100),now=NOW)
    click(repo,router,22,'nav',screen='corpses')
    click(repo,router,22,'loot_corpse',card_id=item)
    assert item in repo.get('g').state.players[22].hand


def test_real_cleric_leader_and_helper_choose_costs_before_entitlement_draw():
    repo,router,ids=fixture()
    s=repo.games['g'].state
    s.players[11].level=8
    for uid,role,cost in [(11,ids['cleric'][0],ids['pretty_balloons'][0]),(22,ids['cleric'][1],ids['rat_on_a_stick'][0])]:
        s.players[uid].role_ids=[role];s.players[uid].in_play=[role];s.players[uid].hand=[cost]
    s.combat.helper_id=22;s.combat.fighter_ids=[11,22];s.combat.help_treasure_count=1
    s.combat.monster_ids=[ids['bigfoot'][0]]
    lamp, shot=ids['magic_lamp'][0],ids['potion_of_idiotic_bravery'][0]
    s.treasure_discard=[lamp,shot]
    s,_=combat.resolve_rewards(s,router.release.catalog,Random(1),now=NOW)
    repo.games['g'].state=s
    for uid,cost in [(11,ids['pretty_balloons'][0]),(22,ids['rat_on_a_stick'][0])]:
        router.route_update(message(uid,uid,'/game',len(repo.receipts)+100),now=NOW)
        click(repo,router,uid,'select',flow='decision')
        click(repo,router,uid,'select',flow='decision',selected=[cost])
        click(repo,router,uid,'respond_decision',choices={'card_ids':[cost]})
        if uid==11:
            assert repo.get('g').state.pending_decision and shot not in repo.get('g').state.players[22].hand
    s=repo.get('g').state
    assert s.combat is None and lamp in s.players[11].hand and shot in s.players[22].hand


def test_hoard_wave_decline_then_resurrection_uses_new_decision_id():
    repo,router,ids=fixture()
    s=repo.games['g'].state
    role,cost,hoard,discard=(ids[k][0] for k in ('cleric','pretty_balloons','hoard','magic_lamp'))
    s.players[11].role_ids=[role];s.players[11].in_play=[role];s.players[11].hand=[cost]
    s.combat.helper_id=22;s.combat.fighter_ids=[11,22]
    s.treasure_deck=[ids['rat_on_a_stick'][0],ids['loaded_die'][0],hoard]
    s.treasure_discard=[discard]
    s,_=combat.resolve_rewards(s,router.release.catalog,Random(1),now=NOW)
    repo.games['g'].state=s
    router.route_update(message(11,11,'/game',100),now=NOW)
    click(repo,router,11,'select',flow='decision')
    old=click(repo,router,11,'respond_decision',choices={'card_ids':[]})
    assert repo.get('g').state.pending_decision.id!=old.args['decision_id']
    click(repo,router,11,'select',flow='decision')
    click(repo,router,11,'select',flow='decision',selected=[cost])
    click(repo,router,11,'respond_decision',choices={'card_ids':[cost]})
    s=repo.get('g').state
    assert s.combat is None and discard in s.players[11].hand and s.treasure_discard.count(hoard)==1


def test_intentional_identity_replacement_keeps_super_munchkin_and_counters():
    repo,router,ids=fixture()
    s=repo.games['g'].state
    old,new=ids['warrior'][:2];supercard=ids['super_munchkin'][0]
    p=s.players[11];p.role_ids=[old];p.in_play=[old,supercard];p.hand=[new];s.combat.ability_uses={(11,'warrior_berserk',None):2}
    play_menu(repo,router,11,new)
    click(repo,router,11,'play_card',card_id=new,choices={'replace_identity_id':old})
    p=repo.get('g').state.players[11]
    assert p.role_ids==[new] and supercard in p.in_play and repo.get('g').state.combat.ability_uses=={(11,'warrior_berserk',None):2}


def test_ring_third_player_cancels_pending_curse_without_foreign_hand():
    repo,router,ids=fixture('turn.prepare')
    curse,ring,hidden=(ids[k][0] for k in ('curse_lose_a_level','wishing_ring','pretty_balloons'))
    s=repo.games['g'].state;s.players[22].hand=[curse];s.players[33].hand=[ring];s.players[11].hand=[hidden]
    play_menu(repo,router,22,curse)
    click(repo,router,22,'play_card',card_id=curse,target={'player_id':11})
    decision=repo.get('g').state.pending_decision.id
    play_menu(repo,router,33,ring)
    assert hidden not in str(repo.outbox[-1])
    click(repo,router,33,'play_card',card_id=ring,choices={'effect_id':decision})
    s=repo.get('g').state
    assert s.pending_decision is None and s.players[11].level==5 and ring in s.treasure_discard


def test_monster_bribe_cost_and_forced_helper_buttons_reach_core():
    repo,router,ids=fixture()
    s=repo.games['g'].state
    nose,item=(ids[k][0] for k in ('floating_nose','boots_of_butt_kicking'))
    s.combat.monster_ids=[nose];s.players[11].hand=[item]
    router.route_update(message(11,11,'/game',100),now=NOW)
    click(repo,router,11,'select',flow='monster_action',option='bribe')
    click(repo,router,11,'select',flow='monster_action',selected=[item])
    click(repo,router,11,'monster_action',choices={'option':'bribe','card_ids':[item]})
    assert item in repo.get('g').state.treasure_discard
    repo,router,ids=fixture();s=repo.games['g'].state
    knees=ids['kneepads_of_allure'][0];s.players[11].in_play=[knees];s.players[11].equipped=[knees];s.players[22].level=6
    router.route_update(message(11,11,'/game',100),now=NOW)
    click(repo,router,11,'force_help',helper_id=22)
    assert repo.get('g').state.combat.helper_id==22


def test_wall_willing_helper_then_escape_and_historical_clock_loaded_die():
    repo,router,ids=fixture('combat.run_away');s=repo.games['g'].state
    wall,die=ids['instant_wall'][0],ids['loaded_die'][0];enemy=s.combat.monster_ids[0]
    s.players[11].hand=[wall,die];s.combat.helper_id=22;s.combat.fighter_ids=[11,22];s.combat.escape_pending={(11,enemy),(22,enemy)}
    play_menu(repo,router,11,wall)
    click(repo,router,11,'play_card',card_id=wall,choices={'player_ids':[11,22]})
    click(repo,router,22,'select',flow='decision')
    click(repo,router,22,'respond_decision',choices={'option':'decline'})
    assert (11,enemy) in repo.get('g').state.combat.automatic_escapes
    assert (22,enemy) not in repo.get('g').state.combat.automatic_escapes
    repo,router,ids=fixture('combat.run_away');s=repo.games['g'].state
    s.players[11].hand=[die];enemy=s.combat.monster_ids[0];s.combat.escape_pending={(11,enemy)}
    router.route_update(message(11,11,'/game',100),now=NOW)
    click(repo,router,11,'run_away',monster_id=enemy)
    play_menu(repo,router,11,die)
    roll=repo.get('g').state.combat.escape_roll_ids[(11,enemy)]
    click(repo,router,11,'play_card',card_id=die,choices={'roll_id':roll,'result':6})
    assert repo.get('g').state.combat.escape_rolls[(11,enemy)]==6


def test_public_death_and_decision_events_have_explicit_safe_text():
    from dota_dungeon.core.model import Event
    repo,router,ids=fixture()
    cid=ids['pretty_balloons'][0]
    text=router._events(repo.get('g').state,[Event('group','player.died',{'user_id':11,'card_ids':[cid]})],11)[0]['payload']['text']
    assert router.release.presentations[cid].display_name_ru in text
    msg=router._events(repo.get('g').state,[Event('group','decision.required',{'kind':'loss_choice','chooser_ids':[22],'hidden':'SECRET'})],11)[0]['payload']['text']
    assert '22' in msg and 'SECRET' not in msg

def test_help_me_out_cost_selector_reachable_when_slots_require_discard():
    repo,router,ids=fixture();s=repo.games['g'].state
    helpcard=ids['help_me_out_here'][0]
    # Pick actual legal equal-slot items with a stronger replacement.
    old=ids['leather_armor'][0];new=ids['mithril_armor'][0]
    s.players[11].level=7;s.combat.monster_ids=[ids['face_sucker'][0]]
    s.players[11].hand=[helpcard];s.players[11].in_play=[old];s.players[11].equipped=[old]
    s.players[22].in_play=[new]
    play_menu(repo,router,11,helpcard)
    click(repo,router,11,'select',flow='play',discard_ids=[old])
    click(repo,router,11,'play_card',card_id=helpcard,target={'player_id':22,'card_id':new},choices={'discard_ids':[old]})
    s=repo.get('g').state
    assert new in s.players[11].equipped and old in s.treasure_discard and new not in s.players[22].in_play


def test_public_profile_hand_allowance_and_group_pending_wait_are_visible():
    repo,router,ids=fixture('turn.prepare');s=repo.games['g'].state
    dwarf=ids['dwarf'][0];s.players[22].race_ids=[dwarf];s.players[22].in_play=[dwarf]
    assert 'Лимит руки: 6' in render_view(s,11,'profile:22',router.release,now=NOW).text
    curse=ids['curse_lose_a_level'][0];s.players[22].hand=[curse]
    play_menu(repo,router,22,curse);click(repo,router,22,'play_card',card_id=curse,target={'player_id':11})
    view=render_view(repo.get('g').state,22,'group',router.release,now=NOW)
    assert '11' in view.text and 'проклятие' in view.text.lower()
    assert not any(b.action=='open_door' for row in view.rows for b in row)


def test_illusion_virtual_foe_and_transferral_distinguish_turn_owner_from_leader():
    repo,router,ids=fixture();s=repo.games['g'].state
    mate,illusion,replacement,transfer=(ids[k][0] for k in ('mate','illusion','potted_plant','transferral_potion'))
    enemy=s.combat.monster_ids[0];s.players[22].hand=[mate,illusion,replacement,transfer]
    play_menu(repo,router,22,mate);click(repo,router,22,'play_card',card_id=mate,target={'monster_id':enemy})
    virtual=next(iter(repo.get('g').state.combat.virtual_monsters))
    play_menu(repo,router,22,illusion)
    click(repo,router,22,'play_card',card_id=illusion,target={'monster_id':virtual},choices={'replacement_card_id':replacement})
    assert replacement in repo.get('g').state.combat.monster_ids and virtual not in repo.get('g').state.combat.monster_ids
    play_menu(repo,router,22,transfer);click(repo,router,22,'play_card',card_id=transfer,target={'player_id':33})
    s=repo.get('g').state
    assert s.active_user_id==11 and s.combat.leader_id==33
    group=render_view(s,11,'group',router.release,now=NOW)
    assert any(b.action=='declare_win' and b.actor_id==33 for row in group.rows for b in row)


def test_undead_from_hand_joins_combat_and_strength_potion_selects_monsters():
    repo,router,ids=fixture();s=repo.games['g'].state
    foe,extra,potion=(ids[k][0] for k in ('undead_horse','wight_brothers','potion_of_idiotic_bravery'))
    s.combat.monster_ids=[foe];s.players[22].hand=[extra,potion]
    play_menu(repo,router,22,extra);click(repo,router,22,'join_undead',card_id=extra)
    assert extra in repo.get('g').state.combat.monster_ids
    before=combat.combat_totals(repo.get('g').state,router.release.catalog)
    play_menu(repo,router,22,potion);click(repo,router,22,'play_card',card_id=potion,choices={'side':'monsters'})
    after=combat.combat_totals(repo.get('g').state,router.release.catalog)
    assert after[0]==before[0] and after[1]==before[1]+2

def test_optional_decision_and_escape_callbacks_expire_at_core_deadline():
    repo,router,ids=fixture('turn.prepare');s=repo.games['g'].state
    curse=ids['curse_lose_a_level'][0];s.players[22].hand=[curse]
    play_menu(repo,router,22,curse);click(repo,router,22,'play_card',card_id=curse,target={'player_id':11})
    click(repo,router,11,'select',flow='decision')
    continue_button=button(repo,'respond_decision',actor=11)
    assert continue_button.expires_at==NOW+timedelta(seconds=30)
    before=repo.get('g')
    router.route_update(press(continue_button,11,900),now=NOW+timedelta(seconds=31))
    assert repo.get('g').state==before.state and repo.get('g').rng.getstate()==before.rng.getstate()
    repo,router,ids=fixture('combat.run_away');s=repo.games['g'].state
    enemy=s.combat.monster_ids[0];s.combat.escape_pending={(11,enemy)}
    router.route_update(message(11,11,'/game',100),now=NOW);click(repo,router,11,'run_away',monster_id=enemy)
    resolve=button(repo,'resolve_escape',actor=11)
    assert resolve.expires_at==NOW+timedelta(seconds=30)
    before=repo.get('g')
    router.route_update(press(resolve,11,900),now=NOW+timedelta(seconds=31))
    assert repo.get('g').state==before.state

def test_host_ending_remains_available_after_optional_decision_deadline():
    from dota_dungeon.telegram.views import render_endgame_confirmation
    repo,router,ids=fixture('turn.prepare');s=repo.games['g'].state
    curse=ids['curse_lose_a_level'][0];s.players[22].hand=[curse]
    play_menu(repo,router,22,curse);click(repo,router,22,'play_card',card_id=curse,target={'player_id':11})
    snapshot=repo.get('g');late=NOW+timedelta(seconds=40)
    _,callbacks=router.outgoing_view(snapshot,render_endgame_confirmation(snapshot.state,11),late)
    assert all(c.expires_at>late for c in callbacks)

def test_real_thief_private_cost_then_loaded_die_theft_continuation():
    repo,router,ids=fixture('turn.prepare');s=repo.games['g'].state
    thief,cost,die,item=(ids[k][0] for k in ('thief','pretty_balloons','loaded_die','magic_missile'))
    p=s.players[11];p.role_ids=[thief];p.in_play=[thief];p.hand=[cost,die];s.players[22].in_play=[item]
    router.route_update(message(11,11,'/game',100),now=NOW)
    click(repo,router,11,'select',ability_key='thief_theft')
    click(repo,router,11,'select',ability_key='thief_theft',cost_ids=[cost])
    click(repo,router,11,'use_ability',ability_key='thief_theft',target={'player_id':22,'card_id':item})
    assert cost in repo.get('g').state.treasure_discard and repo.get('g').state.pending_decision.kind=='die_response'
    play_menu(repo,router,11,die)
    roll=repo.get('g').state.pending_decision.id
    click(repo,router,11,'play_card',card_id=die,choices={'roll_id':roll,'result':6})
    click(repo,router,11,'select',flow='decision');click(repo,router,11,'respond_decision',choices={})
    assert item in repo.get('g').state.players[11].in_play and item not in repo.get('g').state.players[22].in_play


@pytest.mark.parametrize('rule', ['pollymorph_potion','magic_lamp','potion_of_halitosis'])
def test_monster_removal_selectors_resolve_printed_targets(rule):
    repo,router,ids=fixture();s=repo.games['g'].state
    card=ids[rule][0];enemy=ids['floating_nose'][0]
    s.combat.monster_ids=[enemy];s.players[11].hand=[card]
    s.treasure_deck=[ids[k][0] for k in ('pretty_balloons','rat_on_a_stick','loaded_die')]
    play_menu(repo,router,11,card)
    click(repo,router,11,'play_card',card_id=card,target={'monster_id':enemy})
    s=repo.get('g').state
    assert s.combat is None and s.players[11].level==(6 if rule=='potion_of_halitosis' else 5)
    assert card in s.treasure_discard


def test_dowsing_and_ring_choose_exact_persistent_curse():
    repo,router,ids=fixture('turn.prepare');s=repo.games['g'].state
    wand,ring,curse=(ids[k][0] for k in ('wand_of_dowsing','wishing_ring','curse_chicken_on_your_head'))
    s.players[11].hand=[wand];s.players[22].in_play=[curse];s.treasure_discard=[ring]
    play_menu(repo,router,11,wand);click(repo,router,11,'play_card',card_id=wand,target={'card_id':ring})
    assert ring in repo.get('g').state.players[11].hand
    play_menu(repo,router,11,ring)
    click(repo,router,11,'play_card',card_id=ring,target={'player_id':22},choices={'curse_id':curse})
    assert curse not in repo.get('g').state.players[22].in_play


def test_invisibility_then_opponent_glue_bind_current_escape_attempt():
    repo,router,ids=fixture('combat.run_away');s=repo.games['g'].state
    invisible,glue=(ids[k][0] for k in ('invisibility_potion','flask_of_glue'))
    enemy=ids['face_sucker'][0];s.combat.monster_ids=[enemy];s.combat.escape_pending={(11,enemy)}
    s.players[11].hand=[invisible];s.players[22].hand=[glue]
    router.route_update(message(11,11,'/game',100),now=NOW);click(repo,router,11,'run_away',monster_id=enemy)
    first=repo.get('g').state.combat.escape_roll_ids[(11,enemy)]
    play_menu(repo,router,11,invisible)
    click(repo,router,11,'play_card',card_id=invisible,choices={'attempt_id':first})
    assert (11,enemy) in repo.get('g').state.combat.automatic_escapes
    second=repo.get('g').state.combat.escape_roll_ids[(11,enemy)]
    play_menu(repo,router,22,glue)
    click(repo,router,22,'play_card',card_id=glue,target={'player_id':11},choices={'attempt_id':second})
    s=repo.get('g').state
    assert (11,enemy) not in s.combat.automatic_escapes and s.combat.escape_roll_ids[(11,enemy)]!=second

def test_kill_hireling_selector_includes_public_hireling_source():
    repo,router,ids=fixture('turn.prepare');s=repo.games['g'].state
    kill,hireling=(ids[k][0] for k in ('kill_the_hireling','hireling'))
    s.players[11].hand=[kill];s.players[22].in_play=[hireling]
    play_menu(repo,router,11,kill)
    click(repo,router,11,'play_card',card_id=kill,target={'player_id':22,'card_id':hireling})
    assert hireling not in repo.get('g').state.players[22].in_play
