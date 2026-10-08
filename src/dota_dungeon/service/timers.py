"""Durable deadlines are regenerated at each committed game version."""
from copy import deepcopy
from datetime import datetime, timedelta
import json

from .store import Mutation, Snapshot


def _help_key(state):
    if not state.combat or not state.combat.pending_help:
        return None
    return json.dumps([state.active_user_id, state.combat.monster_ids, state.combat.pending_help],
                      ensure_ascii=False, separators=(",", ":"))


def refresh_timers(snapshot: Snapshot, mutation: Mutation, now: datetime) -> Mutation:
    if now.utcoffset() is None:
        raise ValueError("deadline requires timezone")
    metadata = deepcopy(snapshot.metadata if mutation.metadata is None else mutation.metadata)
    mutation.metadata = metadata
    mutation.timers = []
    status = mutation.status or snapshot.status
    state = mutation.state
    if status != "active" or state.phase == "game.finished":
        return mutation
    if mutation.activity or "last_action_at" not in metadata:
        metadata["last_action_at"] = now.isoformat()

    def add(kind, suffix, due, args=None):
        mutation.timers.append({"timer_id": f"{state.game_id}:{kind}:{suffix}", "kind": kind,
                                "args": args or {}, "due_at": due})

    combat = state.combat
    decision = getattr(state, "pending_decision", None)
    if decision and decision.kind != "loss_choice":
        add("decision", decision.id, decision.deadline, {"decision_id": decision.id})
    if combat and not decision and getattr(combat, "escape_deadline", None):
        for (user_id, monster_id), roll_id in combat.escape_roll_ids.items():
            if (user_id, monster_id) in combat.escape_rolls:
                add("escape", roll_id, combat.escape_deadline,
                    {"player_id": user_id, "monster_id": monster_id, "roll_id": roll_id})
    if combat and not decision and combat.reaction_deadline:
        eligible = set(state.order) - set(combat.fighter_ids)
        deadline = now if eligible.issubset(combat.passes) else combat.reaction_deadline
        add("reaction", "current", deadline)
    key = _help_key(state)
    if key:
        if metadata.get("help_key") != key:
            metadata["help_deadline"] = (now + timedelta(seconds=60)).isoformat()
        metadata["help_key"] = key
        add("help", "current", datetime.fromisoformat(metadata["help_deadline"]),
            {"helper_id": combat.pending_help[0]})
    else:
        metadata.pop("help_key", None)
        metadata.pop("help_deadline", None)
    for trade in state.trades.values():
        if trade.status == "pending":
            add("trade", trade.id, trade.expires_at, {"trade_id": trade.id})
    if state.phase != "lobby":
        add("idle", "current", datetime.fromisoformat(metadata["last_action_at"]) + timedelta(seconds=300))
    return mutation


def pause_game(snapshot: Snapshot, now: datetime) -> Mutation:
    if snapshot.status != "active" or now.utcoffset() is None:
        raise ValueError("game is not active")
    metadata = deepcopy(snapshot.metadata)
    metadata["paused_at"] = now.isoformat()
    return Mutation(deepcopy(snapshot.state), deepcopy(snapshot.rng), [], metadata=metadata,
                    status="paused")


def resume_game(snapshot: Snapshot, now: datetime) -> Mutation:
    if snapshot.status != "paused" or now.utcoffset() is None:
        raise ValueError("game is not paused")
    metadata = deepcopy(snapshot.metadata)
    paused_at = datetime.fromisoformat(metadata.pop("paused_at"))
    if now < paused_at:
        raise ValueError("resume precedes pause")
    state = deepcopy(snapshot.state)

    def shifted(deadline):
        return now + max(deadline - paused_at, timedelta())

    if state.combat and state.combat.reaction_deadline:
        state.combat.reaction_deadline = shifted(state.combat.reaction_deadline)
    if state.combat and getattr(state.combat, "escape_deadline", None):
        state.combat.escape_deadline = shifted(state.combat.escape_deadline)
    decision = getattr(state, "pending_decision", None)
    if decision:
        decision.deadline = shifted(decision.deadline)
    for trade in state.trades.values():
        if trade.status == "pending":
            trade.expires_at = shifted(trade.expires_at)
    if metadata.get("help_deadline"):
        metadata["help_deadline"] = shifted(datetime.fromisoformat(metadata["help_deadline"])).isoformat()
    return refresh_timers(snapshot, Mutation(state, deepcopy(snapshot.rng), [], metadata=metadata,
                                            status="active"), now)
