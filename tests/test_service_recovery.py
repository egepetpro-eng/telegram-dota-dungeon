from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from random import Random

import pytest

from dota_dungeon.core.model import GameState, Player
from dota_dungeon.service.store import Snapshot, TransactionResult
from dota_dungeon.service.store import StaleAction

from dota_dungeon.service.application import Application, Config
from dota_dungeon.telegram.client import BotAPIError

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.settings = {}
        self.entries = []
        self.sent = {}
        self.retries = {}
        self.failed = {}
        self.unavailable = []

    def setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def claim_outbox(self, **kwargs):
        return [e for e in self.entries if e["id"] not in self.sent and e["id"] not in self.failed]

    def mark_sent(self, entry_id, result):
        self.sent[entry_id] = result

    def retry_outbox(self, entry_id, code, due):
        self.retries[entry_id] = (code, due)

    def fail_outbox(self, entry_id, code):
        self.failed[entry_id] = code

    def unavailable_private(self, user_id):
        self.unavailable.append(user_id)

    def active_user(self, user_id):
        return []

    def enqueue(self, *args, **kwargs):
        return True

    def active_group(self, group_id):
        return self.snapshot if self.snapshot.state.group_id == group_id else None

    def get(self, game_id):
        return self.snapshot

    def apply(self, game_id, version, request_id, transition, **kwargs):
        mutation = transition(self.snapshot)
        self.snapshot = Snapshot(mutation.state, mutation.rng, version + 1,
                                 mutation.metadata or self.snapshot.metadata, mutation.status or self.snapshot.status)
        return TransactionResult(self.snapshot)


class Bot:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def call_once(self, method, payload):
        self.calls.append((method, payload))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Router:
    def __init__(self, fail=False):
        self.fail = fail
        self.handled = []

    def route_update(self, update, *, now):
        if self.fail:
            raise RuntimeError("crash before durable receipt")
        self.handled.append(update["update_id"])

    def mutation_messages(self, *args, **kwargs):
        return [], []


def app(store, bot, router=None):
    return Application(store, bot, router or Router(), SimpleNamespace(catalog={}), clock=lambda: NOW)


def entry(method="sendMessage", chat_id=11):
    return {"id": 1, "game_id": None, "method": method, "payload": {"chat_id": chat_id, "text": "private"}, "attempts": 1}


def test_offset_advances_only_after_durable_route_and_survives_restart():
    store = Store()
    worker = app(store, Bot([]))
    worker.handle_update({"update_id": 90})
    assert app(store, Bot([])).offset == 91
    worker.router.fail = True
    try:
        worker.handle_update({"update_id": 91})
    except RuntimeError:
        pass
    assert store.setting("poll_offset") == 91


def test_blocked_private_chat_marks_unavailable_without_hand_disclosure():
    store = Store()
    store.entries = [entry()]
    worker = app(store, Bot([BotAPIError(403, "blocked")]))
    assert worker.deliver_outbox(NOW) == 0
    assert store.unavailable == [11]
    assert store.failed == {1: "403"}


def test_missing_remote_photo_delivers_same_caption_and_buttons_as_text():
    store = Store()
    item = entry("sendPhoto")
    item["payload"] = {"chat_id": 11, "photo": "https://example.org/image.png", "caption": "owned card", "parse_mode": "HTML", "reply_markup": {"inline_keyboard": []}}
    store.entries = [item]
    bot = Bot([BotAPIError(400, "wrong file"), {"message_id": 7}])
    assert app(store, bot).deliver_outbox(NOW) == 1
    assert bot.calls[-1] == ("sendMessage", {"chat_id": 11, "text": "owned card", "parse_mode": "HTML", "reply_markup": {"inline_keyboard": []}})
    assert store.sent[1] == {"message_id": 7}


def test_rate_limit_persists_next_attempt_instead_of_losing_message():
    store = Store()
    store.entries = [entry()]
    assert app(store, Bot([BotAPIError(429, "slow", 17)])).deliver_outbox(NOW) == 0
    assert store.retries == {1: ("429", NOW + timedelta(seconds=17))}


def test_configuration_repr_and_errors_do_not_expose_secrets():
    config = Config.from_env({"BOT_TOKEN": "secret-token", "DATABASE_URL": "postgres://secret-db", "CATALOG_VERSION": "classic-dota-v1"})
    assert "secret" not in repr(config)


def test_removing_bot_pauses_game_and_readding_requires_explicit_host_resume():
    store = Store()
    state = GameState("g", -100, 11, "turn.prepare", 11, [11, 22], {11: Player(11), 22: Player(22)})
    store.snapshot = Snapshot(state, Random(0), 0)
    worker = app(store, Bot([]))

    def membership(update_id, status):
        return {"update_id": update_id, "my_chat_member": {"chat": {"id": -100, "type": "supergroup"},
                "new_chat_member": {"status": status}}}

    worker.handle_update(membership(1, "left"))
    assert store.snapshot.status == "paused"
    assert store.snapshot.metadata["paused_at"] == NOW.isoformat()
    worker.handle_update(membership(2, "member"))
    assert store.snapshot.status == "paused"
    assert store.snapshot.state.players[11].level == 1
    assert store.setting("poll_offset") == 3


@pytest.mark.parametrize("kind, command_name, operands", [
    ("decision", "expire_decision", {"decision_id": "decision:7"}),
    ("escape", "expire_escape", {"player_id": 22, "monster_id": "foe", "roll_id": "roll:5"}),
])
def test_continuation_timer_uses_trusted_actor_clock_and_closed_identifiers(monkeypatch, kind, command_name, operands):
    import dota_dungeon.service.application as module
    calls = []

    class TimedStore(Store):
        def due_timers(self, **kwargs):
            return [{"timer_id": "current", "game_id": "g", "expected_version": 4,
                     "kind": kind, "args": {**operands, "now": "untrusted", "actor_id": 999}}]

        def cancel_timer(self, *args):
            raise AssertionError("legal continuation should not be cancelled")

        def apply(self, game_id, version, request_id, transition, **kwargs):
            mutation = transition(self.snapshot)
            assert mutation.activity is False
            return TransactionResult(Snapshot(mutation.state, mutation.rng, version + 1))

    def capture(state, command, catalog, rng):
        calls.append(command)
        return state, []

    monkeypatch.setattr(module, "decide", capture)
    store = TimedStore()
    state = GameState("g", -100, 11, "combat.run_away", 11, [11, 22],
                      {11: Player(11), 22: Player(22)})
    store.snapshot = Snapshot(state, Random(42), 4)
    assert app(store, Bot([])).tick_timers(NOW) == 1
    assert len(calls) == 1
    assert calls[0].name == command_name
    assert calls[0].actor_id == 11
    assert calls[0].args == {**operands, "now": NOW}


def test_blocked_private_delivery_keeps_durable_retry_when_pause_version_races():
    class RacingStore(Store):
        raced = False

        def active_user(self, user_id):
            return [self.snapshot]

        def apply(self, game_id, version, request_id, transition, **kwargs):
            if not self.raced:
                self.raced = True
                self.snapshot.version += 1
                raise StaleAction("concurrent legitimate action")
            return super().apply(game_id, version, request_id, transition, **kwargs)

    store = RacingStore()
    state = GameState("g", -100, 11, "turn.prepare", 11, [11, 22],
                      {11: Player(11), 22: Player(22)})
    store.snapshot = Snapshot(state, Random(0), 0)
    store.entries = [entry()]
    worker = app(store, Bot([BotAPIError(403, "blocked"), BotAPIError(403, "blocked")]))
    worker.deliver_outbox(NOW)
    assert store.snapshot.status == "active"
    assert store.failed == {}
    assert store.retries == {1: ("403", NOW + timedelta(seconds=1))}
    worker.deliver_outbox(NOW + timedelta(seconds=1))
    assert store.snapshot.status == "paused"
    assert store.failed == {1: "403"}
