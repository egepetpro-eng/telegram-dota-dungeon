"""Per-game PostgreSQL transactions persist state, receipts, events and outbox."""
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from random import Random

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.model import Event, GameState
from .codec import decode_rng, decode_state, encode_rng, encode_state


class StaleAction(ValueError):
    """A button belongs to an older version of the game."""


class ActiveGameExists(ValueError):
    """The group already has an active lobby or match."""


@dataclass
class Snapshot:
    state: GameState
    rng: Random
    version: int
    metadata: dict = field(default_factory=dict)
    status: str = "active"


@dataclass
class Mutation:
    state: GameState
    rng: Random
    events: list[Event]
    messages: list[dict] = field(default_factory=list)
    timers: list[dict] = field(default_factory=list)
    metadata: dict | None = None
    status: str | None = None
    callbacks: list = field(default_factory=list)
    activity: bool = True


@dataclass(frozen=True)
class TransactionResult:
    snapshot: Snapshot
    duplicate: bool = False


def _snapshot(row):
    return Snapshot(decode_state(row["state"]), decode_rng(row["rng"]), row["version"],
                    row["metadata"], row["status"])


def _message(message):
    if type(message) is not dict or set(message) != {"method", "payload"}:
        raise ValueError("invalid outbox message")
    if message["method"] not in {"sendMessage", "sendPhoto", "editMessageText", "editMessageReplyMarkup", "answerCallbackQuery"}:
        raise ValueError("unsupported outgoing method")
    if type(message["payload"]) is not dict:
        raise ValueError("invalid outgoing payload")


class GameRepository:
    def __init__(self, database_url: str, *, schema: str = "public", scheduler=None):
        self.database_url = database_url
        self.schema = schema
        self.scheduler = scheduler

    def connection(self):
        connection = psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)
        try:
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        except Exception:
            connection.close()
            raise
        return connection

    def migrate(self):
        with self.connection() as connection:
            connection.execute(files(__package__).joinpath("schema.sql").read_text(encoding="utf-8"))

    def create(self, state: GameState, rng: Random, metadata: dict | None = None, *,
               update_id: str | None = None, messages: list | None = None, callbacks: list | None = None):
        try:
            with self.connection() as connection:
                if update_id and not self._receipt(connection, update_id, state.game_id):
                    return False
                connection.execute(
                    "INSERT INTO games(game_id, group_id, active, state, rng, metadata) VALUES (%s,%s,%s,%s,%s,%s)",
                    (state.game_id, state.group_id, state.phase != "game.finished",
                     Jsonb(encode_state(state)), Jsonb(encode_rng(rng)), Jsonb(metadata or {})),
                )
                self._members(connection, state)
                self._outgoing(connection, update_id, state.game_id, messages or [], callbacks or [])
                return True
        except psycopg.errors.UniqueViolation as exc:
            raise ActiveGameExists("group or game already exists") from exc

    @staticmethod
    def _members(connection, state):
        connection.execute("DELETE FROM game_members WHERE game_id=%s", (state.game_id,))
        for user_id in state.players:
            connection.execute("INSERT INTO game_members(game_id,user_id) VALUES (%s,%s)", (state.game_id, user_id))

    @staticmethod
    def _receipt(connection, update_id, game_id):
        row = connection.execute("INSERT INTO update_receipts(update_id,game_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING update_id",
                                 (update_id, game_id)).fetchone()
        return row is not None

    @staticmethod
    def _outgoing(connection, update_id, game_id, messages, callbacks):
        for intent in callbacks:
            if intent.expires_at.utcoffset() is None or (game_id is not None and intent.game_id != game_id):
                raise ValueError("invalid callback context")
            connection.execute("INSERT INTO callback_intentions(token,game_id,expected_version,actor_id,chat_id,action,args,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                               (intent.token, intent.game_id, intent.expected_version, intent.actor_id, intent.chat_id,
                                intent.action, Jsonb(intent.args), intent.expires_at))
        for ordinal, message in enumerate(messages):
            _message(message)
            connection.execute("INSERT INTO outbox(game_id,update_id,ordinal,method,payload) VALUES (%s,%s,%s,%s,%s)",
                               (game_id, update_id, ordinal, message["method"], Jsonb(message["payload"])))

    def enqueue(self, update_id, messages, *, callbacks=None, game_id=None, private_link=None):
        with self.connection() as connection:
            if not self._receipt(connection, update_id, game_id):
                return False
            if private_link is not None:
                self._link_private(connection, *private_link)
            self._outgoing(connection, update_id, game_id, messages, callbacks or [])
            return True

    def update_seen(self, update_id):
        with self.connection() as connection:
            return connection.execute("SELECT 1 FROM update_receipts WHERE update_id=%s", (update_id,)).fetchone() is not None

    def callback(self, token):
        from ..telegram.callbacks import CallbackIntent
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM callback_intentions WHERE token=%s", (token,)).fetchone()
        return CallbackIntent(**row) if row else None

    @staticmethod
    def _link_private(connection, user_id, chat_id):
        if type(user_id) is not int or user_id <= 0 or chat_id != user_id:
            raise ValueError("invalid private chat identity")
        connection.execute("INSERT INTO private_chats(user_id,chat_id) VALUES (%s,%s) ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id,available=TRUE,updated_at=CURRENT_TIMESTAMP", (user_id, chat_id))

    def link_private(self, user_id, chat_id):
        with self.connection() as connection:
            self._link_private(connection, user_id, chat_id)

    def private_chat(self, user_id):
        with self.connection() as connection:
            row = connection.execute("SELECT chat_id FROM private_chats WHERE user_id=%s AND available", (user_id,)).fetchone()
        return row["chat_id"] if row else None

    def unavailable_private(self, user_id):
        with self.connection() as connection:
            connection.execute("UPDATE private_chats SET available=FALSE,updated_at=CURRENT_TIMESTAMP WHERE user_id=%s", (user_id,))

    def active_user(self, user_id):
        with self.connection() as connection:
            rows = connection.execute("SELECT g.* FROM games g JOIN game_members m USING(game_id) WHERE g.active AND m.user_id=%s ORDER BY g.updated_at DESC", (user_id,)).fetchall()
        return [_snapshot(row) for row in rows]

    def active_games(self):
        with self.connection() as connection:
            return [_snapshot(row) for row in connection.execute("SELECT * FROM games WHERE active").fetchall()]

    def setting(self, key, default=None):
        with self.connection() as connection:
            row = connection.execute("SELECT value FROM service_state WHERE key=%s", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        with self.connection() as connection:
            connection.execute("INSERT INTO service_state(key,value) VALUES (%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, Jsonb(value)))

    @contextmanager
    def singleton(self, name):
        with self.connection() as connection:
            key = self.schema + ":" + name
            acquired = connection.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked", (key,)).fetchone()["locked"]
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))

    def get(self, game_id: str) -> Snapshot:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM games WHERE game_id=%s", (game_id,)).fetchone()
        if row is None:
            raise ValueError("unknown game")
        return _snapshot(row)

    def active_group(self, group_id: int) -> Snapshot | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM games WHERE group_id=%s AND active", (group_id,)).fetchone()
        return _snapshot(row) if row else None

    def apply(self, game_id: str, expected_version: int, update_id: str,
              transition: Callable[[Snapshot], Mutation], *, allow_paused: bool = False) -> TransactionResult:
        if not update_id or type(expected_version) is not int or expected_version < 0:
            raise ValueError("invalid update/version")
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM games WHERE game_id=%s FOR UPDATE", (game_id,)).fetchone()
            if row is None:
                raise ValueError("unknown game")
            receipt = connection.execute("SELECT game_id FROM update_receipts WHERE update_id=%s", (update_id,)).fetchone()
            if receipt:
                if receipt["game_id"] != game_id:
                    raise ValueError("update belongs to another game")
                return TransactionResult(_snapshot(row), duplicate=True)
            if row["version"] != expected_version:
                raise StaleAction("game has changed")
            if row["status"] == "paused" and not allow_paused:
                raise ValueError("game is paused")
            snapshot = _snapshot(row)
            mutation = transition(snapshot)
            if not isinstance(mutation, Mutation):
                raise ValueError("transition must return a mutation")
            if self.scheduler is not None:
                mutation = self.scheduler(snapshot, mutation)
            if (mutation.state.game_id, mutation.state.group_id) != (game_id, row["group_id"]):
                raise ValueError("transition changed game identity")
            for message in mutation.messages:
                _message(message)
            state_data, rng_data = encode_state(mutation.state), encode_rng(mutation.rng)
            metadata = snapshot.metadata if mutation.metadata is None else mutation.metadata
            status = mutation.status or snapshot.status
            if status not in {"active", "paused", "finished"}:
                raise ValueError("invalid service status")
            version = expected_version + 1
            connection.execute("INSERT INTO update_receipts(update_id, game_id) VALUES (%s,%s)", (update_id, game_id))
            connection.execute(
                "UPDATE games SET state=%s,rng=%s,metadata=%s,version=%s,status=%s,active=%s,updated_at=CURRENT_TIMESTAMP WHERE game_id=%s",
                (Jsonb(state_data), Jsonb(rng_data), Jsonb(metadata), version, status,
                 mutation.state.phase != "game.finished" and status != "finished", game_id),
            )
            self._members(connection, mutation.state)
            for event in mutation.events:
                connection.execute("INSERT INTO game_events(game_id,update_id,audience,name,data) VALUES (%s,%s,%s,%s,%s)",
                                   (game_id, update_id, event.audience, event.name, Jsonb(event.data)))
            self._outgoing(connection, update_id, game_id, mutation.messages, mutation.callbacks)
            connection.execute("UPDATE game_timers SET status='cancelled' WHERE game_id=%s AND status='pending'", (game_id,))
            for timer in mutation.timers:
                due = timer.get("due_at")
                if type(due) is not datetime or due.utcoffset() is None:
                    raise ValueError("timer requires timezone deadline")
                connection.execute(
                    "INSERT INTO game_timers(timer_id,game_id,expected_version,kind,args,due_at) VALUES (%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(timer_id) DO UPDATE SET expected_version=excluded.expected_version,args=excluded.args,due_at=excluded.due_at,status='pending'",
                    (timer["timer_id"], game_id, version, timer["kind"], Jsonb(timer.get("args", {})), due),
                )
            return TransactionResult(Snapshot(mutation.state, mutation.rng, version, metadata, status))

    def pending_outbox(self, *, limit: int = 100, now: datetime | None = None) -> list[dict]:
        with self.connection() as connection:
            return connection.execute("SELECT * FROM outbox WHERE sent_at IS NULL AND failed_at IS NULL AND next_attempt_at<=%s ORDER BY id LIMIT %s",
                                      (now or datetime.now(timezone.utc), limit)).fetchall()

    def mark_sent(self, entry_id: int, result: dict):
        with self.connection() as connection:
            connection.execute("UPDATE outbox SET sent_at=CURRENT_TIMESTAMP,result=%s,error_code=NULL,lease_until=NULL WHERE id=%s AND sent_at IS NULL",
                               (Jsonb(result), entry_id))

    def claim_outbox(self, *, limit=100, now=None):
        now = now or datetime.now(timezone.utc)
        with self.connection() as connection:
            return connection.execute(
                "WITH chosen AS (SELECT id FROM outbox WHERE sent_at IS NULL AND failed_at IS NULL AND next_attempt_at<=%s AND (lease_until IS NULL OR lease_until<=%s) ORDER BY id FOR UPDATE SKIP LOCKED LIMIT %s) "
                "UPDATE outbox o SET lease_until=%s,attempts=o.attempts+1 FROM chosen WHERE o.id=chosen.id RETURNING o.*",
                (now, now, limit, now + timedelta(seconds=120))).fetchall()

    def retry_outbox(self, entry_id, error_code, next_attempt_at):
        with self.connection() as connection:
            connection.execute("UPDATE outbox SET error_code=%s,next_attempt_at=%s,lease_until=NULL WHERE id=%s AND sent_at IS NULL", (str(error_code), next_attempt_at, entry_id))

    def fail_outbox(self, entry_id, error_code):
        with self.connection() as connection:
            connection.execute("UPDATE outbox SET failed_at=CURRENT_TIMESTAMP,error_code=%s,lease_until=NULL WHERE id=%s AND sent_at IS NULL", (str(error_code), entry_id))

    def due_timers(self, *, now=None, limit=100):
        with self.connection() as connection:
            return connection.execute("SELECT t.* FROM game_timers t JOIN games g USING(game_id) WHERE t.status='pending' AND g.status='active' AND t.expected_version=g.version AND t.due_at<=%s ORDER BY t.due_at,t.timer_id LIMIT %s", (now or datetime.now(timezone.utc), limit)).fetchall()

    def cancel_timer(self, timer_id, expected_version):
        with self.connection() as connection:
            connection.execute("UPDATE game_timers SET status='cancelled' WHERE timer_id=%s AND expected_version=%s", (timer_id, expected_version))
