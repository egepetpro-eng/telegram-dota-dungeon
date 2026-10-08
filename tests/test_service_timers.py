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


def test_automatic_trade_timeout_does_not_extend_required_action_idle_deadline():
    saved = snapshot()
    saved.metadata["last_action_at"] = NOW.isoformat()
    mutation = Mutation(saved.state, saved.rng, [])
    mutation.activity = False
    changed = refresh_timers(saved, mutation, NOW + timedelta(seconds=120))
    assert next(t for t in changed.timers if t["kind"] == "idle")["due_at"] == NOW + timedelta(seconds=300)


def continuation(saved, kind="curse_response"):
    # Test the frozen adapter contract independently of unfinished core effects.
    from types import SimpleNamespace
    saved.state.pending_decision = SimpleNamespace(
        id="decision:7", kind=kind, deadline=NOW + timedelta(seconds=30))
    return saved


def test_optional_continuation_keeps_deadline_and_defers_combat_closure():
    saved = continuation(snapshot())
    changed = refresh_timers(saved, Mutation(saved.state, saved.rng, []), NOW)
    timer = next(t for t in changed.timers if t["kind"] == "decision")
    assert timer["args"] == {"decision_id": "decision:7"}
    assert timer["due_at"] == NOW + timedelta(seconds=30)
    assert not any(t["kind"] == "reaction" for t in changed.timers)
    again = refresh_timers(Snapshot(changed.state, changed.rng, 8, changed.metadata),
                           Mutation(changed.state, changed.rng, []), NOW + timedelta(seconds=10))
    assert next(t for t in again.timers if t["kind"] == "decision")["due_at"] == timer["due_at"]


def test_mandatory_loss_choice_never_schedules_automatic_card_selection():
    saved = continuation(snapshot(), "loss_choice")
    changed = refresh_timers(saved, Mutation(saved.state, saved.rng, []), NOW)
    assert not any(t["kind"] in {"decision", "reaction"} for t in changed.timers)
    assert next(t for t in changed.timers if t["kind"] == "idle")["due_at"] == NOW + timedelta(seconds=300)


def test_escape_timeout_is_bound_to_current_player_monster_and_roll():
    saved = snapshot()
    saved.state.combat.reaction_deadline = None
    saved.state.combat.escape_rolls = {(22, "monster"): 2}
    saved.state.combat.escape_roll_ids = {(22, "monster"): "roll:5"}
    saved.state.combat.escape_deadline = NOW + timedelta(seconds=30)
    changed = refresh_timers(saved, Mutation(saved.state, saved.rng, []), NOW)
    timer = next(t for t in changed.timers if t["kind"] == "escape")
    assert timer["args"] == {"player_id": 22, "monster_id": "monster", "roll_id": "roll:5"}
    assert timer["due_at"] == NOW + timedelta(seconds=30)


def test_pause_resume_preserves_pending_choice_and_escape_time():
    saved = continuation(snapshot())
    saved.state.combat.escape_deadline = NOW + timedelta(seconds=25)
    paused = pause_game(saved, NOW + timedelta(seconds=10))
    resumed = resume_game(Snapshot(paused.state, paused.rng, 8, paused.metadata, "paused"),
                          NOW + timedelta(hours=1))
    assert resumed.state.pending_decision.deadline == NOW + timedelta(hours=1, seconds=20)
    assert resumed.state.combat.escape_deadline == NOW + timedelta(hours=1, seconds=15)
    assert saved.state.pending_decision.deadline == NOW + timedelta(seconds=30)
