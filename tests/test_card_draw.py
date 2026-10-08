from collections import Counter
from copy import deepcopy
from dataclasses import replace
import importlib
from random import Random

import pytest

from dota_dungeon.core import card_rules
from dota_dungeon.core.combat import resolve_rewards
from dota_dungeon.core.effects import apply_effects
from dota_dungeon.core.engine import decide
from dota_dungeon.core.items import play_identity
from dota_dungeon.core.model import CardDef, CombatState, Command, GameState, Player, RuleError
from dota_dungeon.core.setup import start
from dota_dungeon.core.turn import end_turn, give_charity, loot_room, open_door


def draw(*args):
    module = importlib.import_module('dota_dungeon.core.draw')
    return module.draw_cards(*args)


def fixture():
    # Full, independently verified physical counts; only two trigger definitions
    # and Cleric mechanics are required by this task's tests.
    # Physical inventory copied from the verified Task 1 manifest. Tests are self-contained.
    catalog = {}
    for cid in (
        '3_872_orcs:1 amazon:1 ancient:1 baby:1 bigfoot:1 bullrog:1 cheat:1 cleric:1 cleric:2 cleric:3 '
        'crabs:1 curse_change_class:1 curse_change_race:1 curse_change_sex:1 '
        'curse_chicken_on_your_head:1 curse_duck_of_doom:1 curse_income_tax:1 curse_lose_a_big_item:1 '
        'curse_lose_a_level:1 curse_lose_a_level:2 curse_lose_a_small_item:1 curse_lose_a_small_item:2 '
        'curse_lose_the_armor_you_are_wearing:1 curse_lose_the_footgear_you_are_wearing:1 '
        'curse_lose_the_headgear_you_are_wearing:1 curse_lose_two_cards:1 curse_lose_your_class:1 '
        'curse_lose_your_race:1 curse_malign_mirror:1 divine_intervention:1 drooling_slime:1 dwarf:1 '
        'dwarf:2 dwarf:3 elf:1 elf:2 elf:3 enraged:1 face_sucker:1 floating_nose:1 flying_frogs:1 '
        'gazebo:1 gelatinous_octahedron:1 ghoulfiends:1 half_breed:1 half_breed:2 halfling:1 halfling:2 '
        'halfling:3 harpies:1 help_me_out_here:1 hippogriff:1 humongous:1 illusion:1 '
        'insurance_salesman:1 intelligent:1 king_tut:1 lame_goblin:1 large_angry_chicken:1 lawyers:1 '
        'leperchaun:1 mate:1 maul_rat:1 mr_bones:1 net_troll:1 out_to_lunch:1 pit_bull:1 platycore:1 '
        'plutonium_dragon:1 potted_plant:1 pukachu:1 shrieking_geek:1 snails_on_speed:1 squidzilla:1 '
        'stoned_golem:1 super_munchkin:1 super_munchkin:2 thief:1 thief:2 thief:3 tongue_demon:1 '
        'truly_obnoxious_curse:1 undead_horse:1 unspeakably_awful_indescribable_horror:1 '
        'wandering_monster:1 wandering_monster:2 wandering_monster:3 wannabe_vampire:1 warrior:1 '
        'warrior:2 warrior:3 wight_brothers:1 wizard:1 wizard:2 wizard:3 '
    ).split():
        catalog[cid] = CardDef(cid, 'door', "role" if cid.startswith(("cleric:", "warrior:")) else "special", cid, rule_key=cid.split(":")[0])
    for cid in (
        '1_000_gold_pieces:1 bad_ass_bandana:1 boil_an_anthill:1 boots_of_butt_kicking:1 '
        'boots_of_running_really_fast:1 bow_with_ribbons:1 bribe_gm_with_food:1 broad_sword:1 '
        'buckler_of_swashing:1 chainsaw_of_bloody_dismemberment:1 cheese_grater_of_peace:1 '
        'cloak_of_obscurity:1 convenient_addition_error:1 cotion_of_ponfusion:1 dagger_of_treachery:1 '
        'doppleganger:1 electric_radioactive_acid_potion:1 eleven_foot_pole:1 flaming_armor:1 '
        'flaming_poison_potion:1 flask_of_glue:1 freezing_explosive_potion:1 friendship_potion:1 '
        'gentleman_s_club:1 hammer_of_kneecapping:1 helm_of_courage:1 hireling:1 hoard:1 horny_helmet:1 '
        'huge_rock:1 instant_wall:1 invisibility_potion:1 invoke_obscure_rules:1 kill_the_hireling:1 '
        'kneepads_of_allure:1 leather_armor:1 limburger_and_anchovy_sandwich:1 loaded_die:1 '
        'mace_of_sharpness:1 magic_lamp:1 magic_missile:1 mithril_armor:1 mutilate_the_bodies:1 '
        'nasty_tasting_sports_drink:1 pantyhose_of_giant_strength:1 pointy_hat_of_power:1 '
        'pollymorph_potion:1 potion_of_general_studliness:1 potion_of_halitosis:1 '
        'potion_of_idiotic_bravery:1 pretty_balloons:1 rapier_of_unfairness:1 rat_on_a_stick:1 '
        'really_impressive_title:1 sandals_of_protection:1 shield_of_ubiquity:1 short_wide_armor:1 '
        'singing_dancing_sword:1 sleep_potion:1 slimy_armor:1 sneaky_bastard_sword:1 spiky_knees:1 '
        'staff_of_napalm:1 steal_a_level:1 stepladder:1 swiss_army_polearm:1 transferral_potion:1 '
        'tuba_of_charm:1 wand_of_dowsing:1 whine_at_the_gm:1 wishing_ring:1 wishing_ring:2 '
        'yuppie_water:1 '
    ).split():
        catalog[cid] = CardDef(cid, 'treasure', "role" if cid.startswith(("cleric:", "warrior:")) else "special", cid, rule_key=cid.split(":")[0])
    catalog["potted_plant:1"] = replace(catalog["potted_plant:1"], kind="monster", bonus=1, treasures=1)
    catalog["divine_intervention:1"] = replace(catalog["divine_intervention:1"],
        effects=[{"op": "special", "rule_key": "all_clerics_gain_level",
                  "args": {"amount": 1, "can_win": True, "alert_if_in_hand": True}}],
        trigger={"rule_key": "mandatory_play", "timing": "acquired", "visibility": "group", "args": {}})
    catalog["hoard:1"] = replace(catalog["hoard:1"],
        effects=[{"op": "draw", "deck": "treasure", "amount": 3}],
        trigger={"rule_key": "hoard", "timing": "acquired", "visibility": "inherit",
                 "args": {"include_initial_deal": True}})
    state = GameState('g', -1, 1, 'turn.prepare', 1, [1, 2], {1: Player(1), 2: Player(2)},
        door_deck=[cid for cid,c in catalog.items() if c.deck == 'door'],
        treasure_deck=[cid for cid,c in catalog.items() if c.deck == 'treasure'],
        card_decks={cid:c.deck for cid,c in catalog.items()})
    return state, catalog


def move(state, cid, destination):
    for zone in (state.door_deck, state.treasure_deck):
        if cid in zone:
            zone.remove(cid)
    destination.append(cid)


def zones(state, catalog):
    physical = state.door_deck + state.treasure_deck + state.door_discard + state.treasure_discard
    physical += [cid for p in state.players.values() for cid in p.hand + p.in_play]
    physical += [cid for cards in state.corpse.values() for cid in cards]
    if state.combat:
        physical += state.combat.monster_ids + state.combat.played_card_ids
    assert Counter(physical) == Counter(catalog.keys())
    assert len(physical) == 168


def top(state, deck, ids):
    stack = getattr(state, f'{deck}_deck')
    for cid in ids:
        stack.remove(cid)
    stack.extend(reversed(ids))


def test_hidden_loot_mandatory_trigger_reveals_only_source():
    state, catalog = fixture()
    move(state, 'cleric:1', state.players[2].in_play)
    state.players[2].role_ids = ['cleric:1']
    move(state, 'warrior:1', state.players[1].hand)
    top(state, 'door', ['divine_intervention:1'])
    state.phase = 'turn.after_door'
    result, events = loot_room(state, 1, Random(1), catalog=catalog)
    assert result.players[2].level == 2
    assert result.players[1].hand == ['warrior:1']
    assert 'divine_intervention:1' in result.door_discard
    assert any(e.audience == 'group' and e.data.get('card_id') == 'divine_intervention:1' for e in events)
    assert not any(e.audience == 'group' and 'warrior:1' in str(e.data) for e in events)
    zones(result, catalog)


@pytest.mark.parametrize('face_up,audience', [(False, 'user:1'), (True, 'group')])
def test_hoard_additional_draws_inherit_visibility(face_up, audience):
    state,catalog = fixture()
    top(state,'treasure',['hoard:1', 'boil_an_anthill:1', 'bribe_gm_with_food:1', 'convenient_addition_error:1'])
    result,events = draw(state,1,'treasure',1,face_up,catalog,Random(1))
    assert len(result.players[1].hand) == 3
    assert result.treasure_discard == ['hoard:1']
    assert all(e.audience == audience for e in events if e.name == 'card.drawn')
    zones(result,catalog)


def test_draw_spans_depleted_pile_and_only_recycles_same_deck():
    state,catalog=fixture()
    chosen=state.treasure_deck[-2:]
    state.players[2].hand.extend(state.treasure_deck[:-2])
    state.treasure_deck=chosen[:1]
    state.treasure_discard=chosen[1:]
    move(state,'warrior:1',state.door_discard)
    result,events=draw(state,1,'treasure',3,False,catalog,Random(8))
    assert set(result.players[1].hand) == set(chosen)
    assert result.door_discard == ['warrior:1']
    unavailable=next(e for e in events if e.name=='draw_unavailable')
    assert unavailable.data['missing_count']==1
    assert unavailable.audience=='user:1'
    zones(result,catalog)


def test_trigger_cannot_reprocess_its_discarded_instance_in_same_draw_chain():
    state,catalog=fixture()
    state.players[2].hand.extend(cid for cid in state.treasure_deck if cid!='hoard:1')
    state.treasure_deck=['hoard:1']
    result,events=draw(state,1,'treasure',2,False,catalog,Random(1))
    assert result.treasure_discard==['hoard:1']
    assert sum(e.name=='card.triggered' for e in events)==1
    assert result.players[1].hand==[]
    assert [e.data['missing_count'] for e in events if e.name=='draw_unavailable']==[3,1]
    zones(result,catalog)


def test_public_helped_hoard_rewards_enlarge_pool_before_share():
    state,catalog=fixture()
    catalog['potted_plant:1']=replace(catalog['potted_plant:1'],treasures=2)
    move(state,'potted_plant:1',[])
    state.combat=CombatState(fighter_ids=[1,2],helper_id=2,help_treasure_count=2,monster_ids=['potted_plant:1'])
    state.phase='combat.active'
    top(state,'treasure',['hoard:1','boil_an_anthill:1','bribe_gm_with_food:1','convenient_addition_error:1','invoke_obscure_rules:1'])
    result,events=resolve_rewards(state,catalog,Random(1))
    assert len(result.players[2].hand)==2
    assert len(result.players[1].hand)==2
    assert all(e.audience=='group' for e in events if e.name=='treasure.drawn')
    zones(result,catalog)


def test_partially_fulfilled_rewards_keep_draws_and_levels():
    state,catalog=fixture()
    catalog['potted_plant:1']=replace(catalog['potted_plant:1'],treasures=2)
    move(state,'potted_plant:1',[])
    state.combat=CombatState(fighter_ids=[1],monster_ids=['potted_plant:1'])
    state.phase='combat.active'
    sole='boil_an_anthill:1'
    state.players[2].hand.extend(cid for cid in state.treasure_deck if cid!=sole)
    state.treasure_deck=[sole]
    result,events=resolve_rewards(state,catalog,Random(1))
    assert result.players[1].hand==[sole]
    assert result.players[1].level==2
    assert result.phase=='turn.charity'
    assert any(e.name=='draw_unavailable' and e.data['missing_count']==1 for e in events)
    zones(result,catalog)


def test_empty_door_progresses_without_rejecting():
    state,catalog=fixture()
    state.players[2].hand=state.door_deck
    state.door_deck=[]
    result,events=open_door(state,1,catalog,Random(1))
    assert result.phase=='turn.after_door'
    assert any(e.name=='draw_unavailable' for e in events)
    zones(result,catalog)


class OrderedDeal(Random):
    def shuffle(self, stack):
        # Deal Divine to player1, Cleric to player2, Hoard to player1.
        wanted=['divine_intervention:1'] if 'divine_intervention:1' in stack else ['hoard:1']
        if 'cleric:1' in stack:
            stack.remove('cleric:1')
            stack.insert(len(stack)-3,'cleric:1')
        for cid in wanted:
            stack.remove(cid)
            stack.append(cid)


def test_initial_hands_all_dealt_before_hoard_and_divine_choice():
    state,catalog=fixture()
    state.phase='lobby'
    state.active_user_id=None
    for p in state.players.values(): p.ready=True
    result,events=start(state,1,catalog,OrderedDeal(1))
    assert len(result.players[1].hand)==10 # Divine pending, Hoard replaced by 3
    assert len(result.players[2].hand)==8
    assert result.players[2].level==1
    assert 'cleric:1' in result.players[2].hand
    assert result.pending_initial_triggers==[(1,'divine_intervention:1')]
    result,_=play_identity(result,2,'cleric:1',catalog)
    result,_=open_door(result,result.active_user_id,catalog,Random(2))
    assert result.players[2].level==2
    assert result.pending_initial_triggers==[]
    zones(result,catalog)


def test_rebirth_uses_hidden_trigger_pipeline():
    state,catalog=fixture()
    state.phase='turn.charity'
    state.players[2].alive=False
    top(state,'treasure',['hoard:1'])
    result,events=end_turn(state,1,Random(1),catalog=catalog)
    assert result.players[2].alive
    assert len(result.players[2].hand)==10
    assert all(e.audience=='user:2' for e in events if e.name=='card.drawn')
    zones(result,catalog)


def test_draw_effect_keeps_partial_draw():
    state,catalog=fixture()
    sole=state.treasure_deck[-1]
    state.players[2].hand=state.treasure_deck[:-1]
    state.treasure_deck=[sole]
    result,events=apply_effects(state,1,[{'op':'draw','amount':2}],catalog,rng=Random(3))
    assert result.players[1].hand==[sole]
    assert any(e.name=='draw_unavailable' for e in events)
    zones(result,catalog)


def test_failed_effect_after_random_recycle_preserves_input_and_rng():
    state,catalog=fixture()
    state.treasure_discard=state.treasure_deck
    state.treasure_deck=[]
    state.players[1].level=9
    before=deepcopy(state)
    rng=Random(7)
    rng_before=rng.getstate()
    with pytest.raises(RuleError):
        apply_effects(state,1,[{'op':'draw'}, {'op':'gain_level'}],catalog,rng=rng)
    assert state==before
    assert rng.getstate()==rng_before


@pytest.mark.parametrize('registry,key,bad', [
    ('TRIGGER_HANDLERS','hoard',{'include_initial_deal':False}),
    ('TRIGGER_HANDLERS','mandatory_play',{'unknown':1}),
    ('SPECIAL_HANDLERS','all_clerics_gain_level',{'amount':True,'can_win':True,'alert_if_in_hand':True}),
])
def test_real_trigger_validators_reject_bad_source_args(registry,key,bad):
    importlib.import_module('dota_dungeon.core.draw')
    rule=getattr(card_rules,registry)[key]
    with pytest.raises(ValueError): rule.validate_args(bad)


def test_charity_one_excess_card_allows_zero_share_for_tied_lowest():
    state, catalog = fixture()
    state.order.append(3)
    state.players[3] = Player(3)
    state.players[1].level = 2
    for cid in state.door_deck[-6:]:
        move(state, cid, state.players[1].hand)
    state.phase = 'turn.charity'
    cid = state.players[1].hand[-1]
    result, _ = give_charity(state, 1, {2: [cid], 3: []})
    assert len(result.players[1].hand) == 5
    assert result.players[2].hand == [cid]
    assert result.players[3].hand == []
    zones(result, catalog)


def test_initial_only_trigger_does_not_fire_on_later_acquisition():
    state, catalog = fixture()
    catalog['hoard:1'] = replace(catalog['hoard:1'], trigger={
        **catalog['hoard:1'].trigger, 'timing': 'initial_deal'})
    top(state, 'treasure', ['hoard:1'])
    result, events = draw(state, 1, 'treasure', 1, False, catalog, Random(1))
    assert result.players[1].hand == ['hoard:1']
    assert not any(e.name == 'card.triggered' for e in events)
    zones(result, catalog)


def test_engine_loot_trigger_replay_preserves_rng_and_one_zone():
    state, catalog = fixture()
    move(state, 'cleric:1', state.players[2].in_play)
    state.players[2].role_ids = ['cleric:1']
    state.phase = 'turn.after_door'
    top(state, 'door', ['divine_intervention:1'])
    command = Command('g', 1, 'loot-trigger', 'loot_room')
    rng = Random(9)
    result, events = decide(state, command, catalog, rng)
    before_rng = rng.getstate()
    repeated, repeated_events = decide(result, command, catalog, rng)
    assert repeated is result and repeated_events == []
    assert repeated.players[2].level == 2
    assert rng.getstate() == before_rng
    zones(repeated, catalog)


def test_divine_all_active_clerics_can_win_without_revealing_hidden_cards():
    state, catalog = fixture()
    for user_id, cid in [(1, 'cleric:1'), (2, 'cleric:2')]:
        move(state, cid, state.players[user_id].in_play)
        state.players[user_id].role_ids = [cid]
        state.players[user_id].level = 9
        catalog[cid] = replace(catalog[cid], name='Localized hero')
    move(state, 'cleric:3', state.players[1].hand)
    top(state, 'door', ['divine_intervention:1'])
    result, events = open_door(state, 1, catalog, Random(1))
    assert result.phase == 'game.finished'
    assert [result.players[u].level for u in [1,2]] == [10,10]
    assert {e.data['user_id'] for e in events if e.name == 'game.won'} == {1,2}
    assert not any('cleric:3' in str(e.data) for e in events if e.audience == 'group')
    zones(result, catalog)


def test_opened_persistent_curse_remains_in_play_in_one_zone():
    state, catalog = fixture()
    cid = 'curse_chicken_on_your_head:1'
    catalog[cid] = replace(catalog[cid], kind='curse', effects=[{'op': 'persistent'}])
    top(state, 'door', [cid])
    before = deepcopy(state)
    rng = Random(3)
    rng_before = rng.getstate()

    result, events = open_door(state, 1, catalog, rng)

    from dota_dungeon.core.decisions import respond_decision
    from datetime import datetime,timezone
    result, responses=respond_decision(result,1,result.pending_decision.id,{},catalog,rng,datetime.now(timezone.utc))
    events+=responses
    assert result.phase == 'turn.after_door'
    assert result.players[1].in_play == [cid]
    assert cid not in result.players[1].hand
    assert cid not in result.door_discard
    assert any(e.name == 'door.revealed' and e.audience == 'group'
               and e.data['card_id'] == cid for e in events)
    assert any(e.name == 'decision.required' and e.audience == 'group' for e in events)
    assert state == before
    assert rng.getstate() == rng_before
    zones(result, catalog)
