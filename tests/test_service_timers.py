from datetime import datetime, timedelta, timezone
from random import Random

from dota_dungeon.core.model import CombatState, GameState, Player, Trade
from dota_dungeon.service.store import Mutation, Snapshot
from dota_dungeon.service.timers import refresh_timers, pause_game, resume_game

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def snapshot():
    state = GameState("g", -100, 11, "combat.active", 11, [11, 22, 33],
                      {uid: Player(uid) for uid in [11, 22, 33]})
    state.combat = CombatState(fighter_ids=[11], monster_ids=["monster"],
                              reaction_deadline=NOW + timedelta(seconds=30), pending_help=(22, 1, []))
    state.trades["trade"] = Trade("trade", 22, 33, [], [], NOW + timedelta(seconds=120))
    return Snapshot(state, Random(42), 7, {"reaction_seconds": 30})


def test_refresh_pins_current_deadlines_and_help_keeps_original_expiry():
    saved = snapshot()
    changed = refresh_timers(saved, Mutation(saved.state, saved.rng, []), NOW)
    by_kind = {timer["kind"]: timer for timer in changed.timers}
    assert by_kind["reaction"]["due_at"] == NOW + timedelta(seconds=30)
    assert by_kind["help"]["due_at"] == NOW + timedelta(seconds=60)
    assert by_kind["trade"]["due_at"] == NOW + timedelta(seconds=120)
    assert by_kind["idle"]["due_at"] == NOW + timedelta(seconds=300)
    again = refresh_timers(Snapshot(changed.state, changed.rng, 8, changed.metadata),
                           Mutation(changed.state, changed.rng, []), NOW + timedelta(seconds=10))
    assert next(t for t in again.timers if t["kind"] == "help")["due_at"] == NOW + timedelta(seconds=60)


def test_all_passes_close_early_and_finished_game_has_no_timers():
    saved = snapshot()
    saved.state.combat.passes = {22, 33}
    changed = refresh_timers(saved, Mutation(saved.state, saved.rng, []), NOW)
    assert next(t for t in changed.timers if t["kind"] == "reaction")["due_at"] == NOW
    saved.state.phase = "game.finished"
    assert refresh_timers(saved, Mutation(saved.state, saved.rng, []), NOW).timers == []


def test_pause_resume_preserves_remaining_reaction_help_and_trade():
    saved = snapshot()
    initial = refresh_timers(saved, Mutation(saved.state, saved.rng, []), NOW)
    saved.metadata = initial.metadata
    paused = pause_game(saved, NOW + timedelta(seconds=10))
    assert paused.status == "paused"
    assert paused.timers == []
    assert saved.state.combat.reaction_deadline == NOW + timedelta(seconds=30)
    resumed = resume_game(Snapshot(paused.state, paused.rng, 8, paused.metadata, "paused"), NOW + timedelta(hours=1))
    assert resumed.status == "active"
    assert resumed.state.combat.reaction_deadline == NOW + timedelta(hours=1, seconds=20)
    assert resumed.state.trades["trade"].expires_at == NOW + timedelta(hours=1, seconds=110)
    assert resumed.metadata["help_deadline"] == (NOW + timedelta(hours=1, seconds=50)).isoformat()


def test_paused_game_never_schedules_or_resets_deadlines():
    saved = snapshot()
    saved.status = "paused"
    changed = refresh_timers(saved, Mutation(saved.state, saved.rng, [], status="paused"), NOW)
    assert changed.timers == []
