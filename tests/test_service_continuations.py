"""Real card continuations survive PostgreSQL restart and durable deadlines."""
from datetime import timedelta
from random import Random

from test_service_store import repository
from test_card_catalog_acceptance import NOW, prepared, hand, one_zone
from dota_dungeon.cards.installed import validate_installed_release
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command, CombatState
from dota_dungeon.service.application import Application
from dota_dungeon.service.store import GameRepository, Mutation
from dota_dungeon.service.timers import refresh_timers, resume_game


class Panels:
    def mutation_messages(self, state, *args, **kwargs):
        return [{"method": "sendMessage", "payload": {
            "chat_id": state.group_id, "text": "Продолжение обработано"}}], []


def setup(repository):
    release = validate_installed_release()
    state, _ = prepared(release)
    state.players[1].level = 5
    repository.scheduler = lambda saved, mutation: refresh_timers(saved, mutation, NOW)
    return state, release


def apply(repo, release, action, actor=1, now=NOW, **args):
    saved = repo.get("acceptance")
    request = f"move:{saved.version}:{action}"
    def transition(snapshot):
        state, events = decide(snapshot.state, Command(snapshot.state.game_id, actor,
            request, action, {"now": now, **args}), release.catalog, snapshot.rng)
        one_zone(state, release.catalog)
        return Mutation(state, snapshot.rng, events)
    return repo.apply(saved.state.game_id, saved.version, request, transition).snapshot


def restart(repo, release, now):
    restored = GameRepository(repo.database_url, schema=repo.schema,
        scheduler=lambda saved, mutation: refresh_timers(saved, mutation, now))
    return restored, Application(restored, None, Panels(), release, clock=lambda: now)


def test_pending_curse_source_and_timeout_survive_restart_once(repository):
    state, release = setup(repository)
    hand(state, "curse_lose_a_level:1", 2)
    repository.create(state, Random(42), {"last_action_at": NOW.isoformat()})
    saved = apply(repository, release, "play_card", 2,
        card_id="curse_lose_a_level:1", target={"player_id": 1})
    assert saved.state.players[1].level == 5
    assert saved.state.resolving_card_ids == ["curse_lose_a_level:1"]
    decision_id = saved.state.pending_decision.id
    repo, app = restart(repository, release, NOW + timedelta(seconds=30))
    assert repo.get("acceptance").state.pending_decision.id == decision_id
    assert app.tick_timers() == 1
    assert app.tick_timers() == 0
    result = repo.get("acceptance")
    assert result.state.players[1].level == 4
    assert result.state.pending_decision is None
    assert result.state.resolving_card_ids == []
    assert result.state.door_discard.count("curse_lose_a_level:1") == 1
    assert len(repo.pending_outbox()) == 1
    one_zone(result.state, release.catalog)


def test_deferred_combat_curse_restarts_persisted_reaction_after_reload(repository):
    state, release = setup(repository)
    monster = "lame_goblin:1"
    state.door_deck.remove(monster)
    state.phase = "combat.active"
    state.combat = CombatState(leader_id=1, fighter_ids=[1], monster_ids=[monster])
    hand(state, "curse_lose_a_level:1", 2)
    repository.create(state, Random(42), {"last_action_at": NOW.isoformat()})
    apply(repository, release, "declare_win", seconds=60)
    apply(repository, release, "play_card", 2, now=NOW + timedelta(seconds=20),
        card_id="curse_lose_a_level:1", target={"player_id": 1})
    repo, app = restart(repository, release, NOW + timedelta(seconds=50))
    queued = repo.get("acceptance").state.resolution_queue
    assert {"kind": "reaction", "was_reacting": True} in queued
    assert app.tick_timers() == 1
    saved = repo.get("acceptance").state
    assert saved.players[1].level == 4
    assert saved.combat.reaction_deadline == NOW + timedelta(seconds=110)
    assert not saved.resolution_queue
    repo, app = restart(repo, release, NOW + timedelta(seconds=110))
    assert app.tick_timers() == 1 and app.tick_timers() == 0
    result = repo.get("acceptance").state
    assert result.players[1].level == 5 and result.combat is None
    assert result.door_discard.count(monster) == 1
    assert result.door_discard.count("curse_lose_a_level:1") == 1
    one_zone(result, release.catalog)


def test_mandatory_item_loss_pauses_without_selection_then_resumes_owned_choice(repository):
    state, release = setup(repository)
    hand(state, "curse_lose_a_small_item:1", 2)
    hand(state, "wishing_ring:1", 1)
    hand(state, "loaded_die:1", 1)
    repository.create(state, Random(42), {"last_action_at": NOW.isoformat()})
    apply(repository, release, "play_card", 2,
        card_id="curse_lose_a_small_item:1", target={"player_id": 1})
    saved = apply(repository, release, "respond_decision",
        decision_id=repository.get("acceptance").state.pending_decision.id, choices={})
    assert saved.state.pending_decision.kind == "loss_choice"
    before_hand = saved.state.players[1].hand.copy()
    decision_id = saved.state.pending_decision.id
    repo, app = restart(repository, release, NOW + timedelta(seconds=300))
    assert app.tick_timers() == 1
    paused = repo.get("acceptance")
    assert paused.status == "paused"
    assert paused.state.players[1].hand == before_hand
    assert paused.state.pending_decision.id == decision_id
    resumed_at = NOW + timedelta(hours=1)
    repo.apply("acceptance", paused.version, "resume", lambda snapshot:
        resume_game(snapshot, resumed_at), allow_paused=True)
    chosen = apply(repo, release, "respond_decision", now=resumed_at,
        decision_id=decision_id, choices={"card_ids": ["loaded_die:1"]})
    assert chosen.status == "active" and chosen.state.pending_decision is None
    assert chosen.state.players[1].hand == ["wishing_ring:1"]
    assert chosen.state.treasure_discard.count("loaded_die:1") == 1
    one_zone(chosen.state, release.catalog)


def test_stored_escape_die_can_be_changed_after_restart_then_expires_once(repository):
    state, release = setup(repository)
    monster = "lame_goblin:1"
    state.door_deck.remove(monster)
    state.phase = "combat.run_away"
    state.combat = CombatState(leader_id=1, fighter_ids=[1], monster_ids=[monster],
        escape_pending={(1, monster)})
    hand(state, "loaded_die:1", 1)
    repository.create(state, Random(1), {"last_action_at": NOW.isoformat()})
    saved = apply(repository, release, "run_away", monster_id=monster)
    roll_id = saved.state.combat.escape_roll_ids[(1, monster)]
    assert saved.state.combat.escape_rolls[(1, monster)] == 2
    repo, app = restart(repository, release, NOW + timedelta(seconds=30))
    apply(repo, release, "play_card", now=NOW + timedelta(seconds=10),
        card_id="loaded_die:1", target={}, choices={"roll_id": roll_id, "result": 6})
    assert app.tick_timers() == 1
    assert app.tick_timers() == 0
    result = repo.get("acceptance").state
    assert result.combat is None and result.players[1].level == 5
    assert result.door_discard.count(monster) == 1
    assert result.treasure_discard.count("loaded_die:1") == 1
    one_zone(result, release.catalog)


def test_two_cleric_reward_choices_keep_first_response_across_restart(repository):
    state, release = setup(repository)
    monster = "bigfoot:1"
    state.door_deck.remove(monster)
    for uid in (1, 2):
        role = f"cleric:{uid}"
        state.door_deck.remove(role)
        state.players[uid].in_play = [role]
        state.players[uid].role_ids = [role]
    state.players[1].strength_bonus = 20
    hand(state, "loaded_die:1", 2)
    # A known top discard can be resurrected by the helper's paid choice.
    discard = "pretty_balloons:1"
    state.treasure_deck.remove(discard)
    state.treasure_discard.append(discard)
    state.phase = "combat.active"
    state.combat = CombatState(leader_id=1, fighter_ids=[1, 2], helper_id=2,
        help_treasure_count=1, monster_ids=[monster])
    repository.create(state, Random(42), {"last_action_at": NOW.isoformat()})
    apply(repository, release, "declare_win")
    saved = apply(repository, release, "close_reaction", now=NOW + timedelta(seconds=30))
    assert saved.state.pending_decision.kind == "reward_draw"
    decision_id = saved.state.pending_decision.id
    apply(repository, release, "respond_decision", 2, now=NOW + timedelta(seconds=31),
        decision_id=decision_id, choices={"card_ids": ["loaded_die:1"]})
    repo, app = restart(repository, release, NOW + timedelta(seconds=60))
    pending = repo.get("acceptance").state.pending_decision
    assert pending.responses == {2: {"card_ids": ["loaded_die:1"]}}
    assert app.tick_timers() == 1
    assert app.tick_timers() == 0
    result = repo.get("acceptance").state
    assert result.pending_decision is None and result.combat is None
    assert discard in result.players[2].hand
    assert result.players[1].level == 6
    assert result.treasure_discard.count("loaded_die:1") == 1
    one_zone(result, release.catalog)


def test_hoard_reserved_source_and_second_shared_reward_wave_survive_restart(repository):
    state, release = setup(repository)
    monster = "bigfoot:1"
    state.door_deck.remove(monster)
    for uid in (1, 2):
        role = f"cleric:{uid}"
        state.door_deck.remove(role)
        state.players[uid].in_play = [role]
        state.players[uid].role_ids = [role]
    state.players[1].strength_bonus = 20
    state.treasure_deck.remove("hoard:1")
    state.treasure_deck.append("hoard:1")
    state.phase = "combat.active"
    state.combat = CombatState(leader_id=1, fighter_ids=[1, 2], helper_id=2,
        help_treasure_count=1, monster_ids=[monster])
    repository.create(state, Random(42), {"last_action_at": NOW.isoformat()})
    apply(repository, release, "declare_win")
    apply(repository, release, "close_reaction", now=NOW + timedelta(seconds=30))
    repo, app = restart(repository, release, NOW + timedelta(seconds=60))
    assert app.tick_timers() == 1
    midway = repo.get("acceptance").state
    assert midway.pending_decision.kind == "reward_draw"
    assert "hoard:1" in midway.resolving_card_ids
    assert "hoard:1" not in midway.treasure_discard
    one_zone(midway, release.catalog)
    repo, app = restart(repo, release, NOW + timedelta(seconds=90))
    assert app.tick_timers() == 1 and app.tick_timers() == 0
    result = repo.get("acceptance").state
    assert result.combat is None and result.pending_decision is None
    assert result.resolving_card_ids == []
    assert result.treasure_discard.count("hoard:1") == 1
    assert len(result.players[2].hand) == 1 and len(result.players[1].hand) == 4
    one_zone(result, release.catalog)

def test_helper_item_loss_reloads_and_reaction_settles_once(repository):
    state, release = setup(repository)
    monster, armor, shot = 'large_angry_chicken:1', 'mithril_armor:1', 'magic_missile:1'
    state.door_deck.remove(monster)
    for cid in (armor, shot):
        state.treasure_deck.remove(cid)
        state.players[1].in_play.append(cid)
    state.players[1].equipped = [armor]
    state.players[2].level = 4
    hand(state,'curse_lose_the_armor_you_are_wearing:1',2)
    state.phase = 'combat.active'
    state.combat = CombatState(leader_id=1,fighter_ids=[1],monster_ids=[monster])
    repository.create(state,Random(42),{'last_action_at':NOW.isoformat()})
    apply(repository,release,'ask_help',helper_id=2,treasure_count=0,item_ids=[armor,shot])
    apply(repository,release,'accept_help',2)
    saved = apply(repository,release,'play_card',2,card_id='curse_lose_the_armor_you_are_wearing:1',target={'player_id':1})
    saved = apply(repository,release,'respond_decision',decision_id=saved.state.pending_decision.id,choices={})
    assert saved.state.combat.help_item_ids == [shot]
    repo, app = restart(repository,release,NOW)
    assert repo.get('acceptance').state.combat.help_item_ids == [shot]
    apply(repo,release,'declare_win')
    repo, app = restart(repo,release,NOW+timedelta(seconds=30))
    assert app.tick_timers()==1 and app.tick_timers()==0
    result=repo.get('acceptance').state
    assert result.combat is None and shot in result.players[2].in_play
    assert armor not in result.players[2].in_play
    one_zone(result,release.catalog)


def test_revived_player_keeps_refill_entitlement_through_two_restarts(repository):
    from dota_dungeon.core.loss_rules import death
    from dota_dungeon.core.model import Player
    state,release=setup(repository)
    state.players[3]=Player(3)
    state.order=[1,2,3]
    state.phase='turn.charity'
    # Open and loot role cards on each intervening turn, leaving rebirth draws free.
    doors = ['3_872_orcs:1','amazon:1','bigfoot:1','bullrog:1',
             'warrior:1','wizard:1','warrior:2','wizard:2']
    for cid in doors:
        state.door_deck.remove(cid)
    state.door_deck.extend(doors)
    for cid in ['mithril_armor:1','huge_rock:1','pretty_balloons:1','magic_missile:1']:
        state.treasure_deck.remove(cid)
        state.treasure_deck.append(cid)
    state,_=death(state,1,release.catalog,Random(1))
    repository.create(state,Random(42),{'last_action_at':NOW.isoformat()})
    apply(repository,release,'end_turn')
    repo,app=restart(repository,release,NOW)
    saved=repo.get('acceptance')
    assert saved.state.players[1].alive and saved.state.players[1].rebirth_pending
    assert saved.state.players[1].hand==[]
    # Finish the two intervening ordinary turns through real commands.
    for uid in (2,3):
        apply(repo,release,'open_door',uid)
        # These controlled top doors are ordinary roles, so no combat intervenes.
        saved=repo.get('acceptance')
        if saved.state.combat or saved.state.pending_decision:
            raise AssertionError('choose noncombat top doors in fixture')
        apply(repo,release,'loot_room',uid)
        apply(repo,release,'end_turn',uid)
    repo,app=restart(repo,release,NOW)
    result=repo.get('acceptance').state
    assert result.active_user_id==1 and result.players[1].alive
    assert not result.players[1].rebirth_pending and len(result.players[1].hand)==8
    one_zone(result,release.catalog)
