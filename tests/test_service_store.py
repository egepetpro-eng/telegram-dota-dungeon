"""Real PostgreSQL proves rollback, replay protection and game isolation."""
from concurrent.futures import ThreadPoolExecutor
import os
from random import Random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import psycopg
from psycopg import sql

from dota_dungeon.core.model import Event, GameState, Player


@pytest.fixture
def repository():
    from dota_dungeon.service.store import GameRepository
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for real PostgreSQL integration")
    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(url) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    repo = GameRepository(url, schema=schema)
    repo.migrate()
    yield repo
    with psycopg.connect(url) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def create(repo, game_id="game", group_id=-100):
    state = GameState(game_id, group_id, 11, "turn.prepare", 11, [11, 22],
                      {11: Player(11), 22: Player(22)})
    repo.create(state, Random(42), {"reaction_seconds": 30})
    return state


def level_up(snapshot):
    from dota_dungeon.service.store import Mutation
    snapshot.state.players[11].level += 1
    return Mutation(snapshot.state, snapshot.rng, [Event("group", "changed", {"user_id": 11})],
                    messages=[{"method": "sendMessage", "payload": {"chat_id": snapshot.state.group_id, "text": "changed"}}])


def test_commit_persists_state_rng_and_outbox_together(repository):
    create(repository)
    result = repository.apply("game", 0, "tg:1", level_up)
    assert result.snapshot.version == 1
    assert repository.get("game").state.players[11].level == 2
    assert repository.get("game").metadata == {"reaction_seconds": 30}
    assert len(repository.pending_outbox()) == 1
    assert repository.pending_outbox()[0]["payload"]["chat_id"] == -100
    assert repository.get("game").rng.randrange(1000) == 654


def test_replayed_update_never_reapplies_reward_or_outbox(repository):
    create(repository)
    repository.apply("game", 0, "tg:replay", level_up)
    replay = repository.apply("game", 0, "tg:replay", level_up)
    assert replay.duplicate is True
    assert replay.snapshot.state.players[11].level == 2
    assert len(repository.pending_outbox()) == 1


def test_failure_rolls_back_receipt_state_and_messages(repository):
    create(repository)

    def fail(snapshot):
        snapshot.state.players[11].level = 9
        raise ValueError("rejected move")

    with pytest.raises(ValueError, match="rejected move"):
        repository.apply("game", 0, "tg:retry", fail)
    assert repository.get("game").state.players[11].level == 1
    assert repository.pending_outbox() == []
    assert repository.apply("game", 0, "tg:retry", level_up).duplicate is False


def test_two_simultaneous_actions_accept_only_one_version(repository):
    from dota_dungeon.service.store import StaleAction
    create(repository)

    def attempt(index):
        try:
            repository.apply("game", 0, "tg:" + str(index), level_up)
            return "accepted"
        except StaleAction:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [1, 2])) == ["accepted", "stale"]
    assert repository.get("game").state.players[11].level == 2
    assert len(repository.pending_outbox()) == 1


def test_active_group_uniqueness_and_other_game_isolation(repository):
    from dota_dungeon.service.store import ActiveGameExists
    create(repository)
    with pytest.raises(ActiveGameExists):
        create(repository, "conflict", -100)
    create(repository, "other", -200)
    repository.apply("game", 0, "tg:unique", level_up)
    assert repository.get("other").state.players[11].level == 1


def test_invalid_outbox_message_rolls_back_move(repository):
    from dota_dungeon.service.store import Mutation
    create(repository)

    def bad(snapshot):
        snapshot.state.players[11].level = 9
        return Mutation(snapshot.state, snapshot.rng, [], messages=[{"method": "sendMessage"}])

    with pytest.raises(ValueError):
        repository.apply("game", 0, "tg:bad", bad)
    assert repository.get("game").state.players[11].level == 1
    assert repository.pending_outbox() == []


def test_sent_outbox_stays_sent_after_repository_restart(repository):
    from dota_dungeon.service.store import GameRepository
    create(repository)
    repository.apply("game", 0, "tg:send", level_up)
    entry = repository.pending_outbox()[0]
    repository.mark_sent(entry["id"], {"message_id": 123})
    restarted = GameRepository(repository.database_url, schema=repository.schema)
    assert restarted.pending_outbox() == []
    assert restarted.get("game").state.players[11].level == 2


def test_navigation_callbacks_and_receipt_survive_restart(repository):
    from dota_dungeon.telegram.callbacks import CallbackIntent
    create(repository)
    intent = CallbackIntent("opaque", "game", 0, 11, 11, "nav", {"screen": "hand"},
                            datetime.now(timezone.utc) + timedelta(minutes=5))
    message = {"method": "sendMessage", "payload": {"chat_id": 11, "text": "private"}}
    assert repository.enqueue("tg:nav", [message], callbacks=[intent], game_id="game")
    assert not repository.enqueue("tg:nav", [message], callbacks=[intent], game_id="game")
    assert repository.callback("opaque") == intent
    assert repository.get("game").version == 0
    assert len(repository.pending_outbox()) == 1


def test_private_links_and_membership_are_scoped(repository):
    create(repository)
    create(repository, "other", -200)
    assert repository.private_chat(11) is None
    repository.link_private(11, 11)
    assert repository.private_chat(11) == 11
    assert {s.state.game_id for s in repository.active_user(11)} == {"game", "other"}
    assert repository.active_user(99) == []
    repository.unavailable_private(11)
    assert repository.private_chat(11) is None


def test_outbox_lease_retry_and_permanent_failure(repository):
    create(repository)
    repository.apply("game", 0, "tg:lease", level_up)
    now = datetime.now(timezone.utc)
    entries = repository.claim_outbox(now=now)
    assert len(entries) == 1
    assert repository.claim_outbox(now=now) == []
    repository.retry_outbox(entries[0]["id"], "429", now + timedelta(seconds=10))
    assert repository.claim_outbox(now=now) == []
    assert len(repository.claim_outbox(now=now + timedelta(seconds=11))) == 1
    repository.fail_outbox(entries[0]["id"], "403")
    assert repository.pending_outbox(now=now + timedelta(hours=1)) == []


def test_durable_offset_and_singleton_lock(repository):
    assert repository.setting("poll_offset", 0) == 0
    repository.set_setting("poll_offset", 901)
    assert repository.setting("poll_offset", 0) == 901
    with repository.singleton("poller") as first:
        assert first
        with repository.singleton("poller") as second:
            assert not second


def test_timer_replacement_is_atomic_and_newer_version_invalidates_old_jobs(repository):
    create(repository)
    now = datetime.now(timezone.utc)

    def scheduled(snapshot):
        mutation = level_up(snapshot)
        mutation.timers = [{"timer_id": "game:idle", "kind": "idle", "due_at": now}]
        return mutation

    repository.apply("game", 0, "tg:timer", scheduled)
    assert repository.due_timers(now=now)[0]["expected_version"] == 1
    repository.apply("game", 1, "tg:newer", level_up)
    assert repository.due_timers(now=now) == []


def test_replayed_start_does_not_reenable_blocked_private_chat(repository):
    message = {"method": "sendMessage", "payload": {"chat_id": 11, "text": "linked"}}
    assert repository.enqueue("tg:start", [message], private_link=(11, 11))
    assert repository.update_seen("tg:start")
    assert repository.private_chat(11) == 11
    repository.unavailable_private(11)
    assert not repository.enqueue("tg:start", [message], private_link=(11, 11))
    assert repository.private_chat(11) is None
