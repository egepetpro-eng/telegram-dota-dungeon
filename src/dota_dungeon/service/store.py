"""Per-game PostgreSQL transactions persist state, receipts, events and outbox."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    def __init__(self, database_url: str, *, schema: str = "public"):
        self.database_url = database_url
        self.schema = schema

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

    def create(self, state: GameState, rng: Random, metadata: dict | None = None):
        try:
            with self.connection() as connection:
                connection.execute(
                    "INSERT INTO games(game_id, group_id, active, state, rng, metadata) VALUES (%s,%s,%s,%s,%s,%s)",
                    (state.game_id, state.group_id, state.phase != "game.finished",
                     Jsonb(encode_state(state)), Jsonb(encode_rng(rng)), Jsonb(metadata or {})),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ActiveGameExists("group or game already exists") from exc

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
            for event in mutation.events:
                connection.execute("INSERT INTO game_events(game_id,update_id,audience,name,data) VALUES (%s,%s,%s,%s,%s)",
                                   (game_id, update_id, event.audience, event.name, Jsonb(event.data)))
            for ordinal, message in enumerate(mutation.messages):
                connection.execute("INSERT INTO outbox(game_id,update_id,ordinal,method,payload) VALUES (%s,%s,%s,%s,%s)",
                                   (game_id, update_id, ordinal, message["method"], Jsonb(message["payload"])))
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
            return connection.execute("SELECT * FROM outbox WHERE sent_at IS NULL AND next_attempt_at<=%s ORDER BY id LIMIT %s",
                                      (now or datetime.now(timezone.utc), limit)).fetchall()

    def mark_sent(self, entry_id: int, result: dict):
        with self.connection() as connection:
            connection.execute("UPDATE outbox SET sent_at=CURRENT_TIMESTAMP,result=%s,error_code=NULL WHERE id=%s AND sent_at IS NULL",
                               (Jsonb(result), entry_id))
