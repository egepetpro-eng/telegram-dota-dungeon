"""Long polling, durable outgoing delivery and trusted deadline execution."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import os
import signal
import threading

from ..core.engine import decide
from ..core.model import Command, RuleError
from ..telegram.client import BotAPIError, BotClient
from .store import GameRepository, Mutation, StaleAction
from .timers import pause_game, refresh_timers

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    bot_token: str = field(repr=False)
    database_url: str = field(repr=False)
    catalog_version: str = "classic-dota-v1"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        if not env.get("BOT_TOKEN") or not env.get("DATABASE_URL"):
            raise ValueError("BOT_TOKEN and DATABASE_URL are required")
        level = env.get("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("invalid LOG_LEVEL")
        return cls(env["BOT_TOKEN"], env["DATABASE_URL"], env.get("CATALOG_VERSION", "classic-dota-v1"), level)


class Application:
    def __init__(self, repository, bot, router, release, *, clock=None):
        self.repository, self.bot, self.router, self.release = repository, bot, router, release
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.offset = repository.setting("poll_offset", 0)
        self.stop = threading.Event()

    def handle_update(self, update):
        update_id = update.get("update_id")
        if type(update_id) is not int or update_id < 0:
            raise ValueError("invalid Telegram update id")
        if update_id < self.offset:
            return
        if "my_chat_member" in update:
            self._membership(update, self.clock())
        else:
            self.router.route_update(update, now=self.clock())
        # Router returns only after commit (or a durably recorded rejection).
        self.repository.set_setting("poll_offset", update_id + 1)
        self.offset = update_id + 1

    def _membership(self, update, now):
        change = update["my_chat_member"]
        chat = change.get("chat", {})
        request = f"telegram:{update['update_id']}"
        if chat.get("type") not in {"group", "supergroup"} or type(chat.get("id")) is not int:
            self.repository.enqueue(request, [])
            return
        snapshot = self.repository.active_group(chat["id"])
        membership = change.get("new_chat_member", {})
        present = membership.get("status") in {"member", "administrator"} or (
            membership.get("status") == "restricted" and membership.get("is_member") is True)
        if snapshot is None:
            self.repository.enqueue(request, [])
            return
        if not present and snapshot.status == "active":

            def transition(current):
                return pause_game(current, now)

            self.repository.apply(snapshot.state.game_id, snapshot.version, request, transition)
        else:
            messages = []
            if present and snapshot.status == "paused":
                messages = [{"method": "sendMessage", "payload": {"chat_id": chat["id"],
                    "text": "Бот снова в группе. Партия сохранена и остаётся на паузе. Ведущий может продолжить через /resume."}}]
            self.repository.enqueue(request, messages, game_id=snapshot.state.game_id)

    def _pause_unavailable(self, entry, now):
        chat_id = entry["payload"].get("chat_id")
        if type(chat_id) is not int:
            return
        if chat_id > 0:
            self.repository.unavailable_private(chat_id)
            snapshots = self.repository.active_user(chat_id)
        elif entry.get("game_id"):
            snapshots = [self.repository.get(entry["game_id"])]
        else:
            snapshots = []
        for snapshot in snapshots:
            if snapshot.status != "active":
                continue

            def transition(current):
                mutation = pause_game(current, now)
                mutation.messages, mutation.callbacks = self.router.mutation_messages(
                    mutation.state, current.version + 1, mutation.metadata, [], now, status="paused")
                if chat_id > 0:
                    mutation.messages.insert(0, {"method": "sendMessage", "payload": {
                        "chat_id": current.state.group_id,
                        "text": "Партия на паузе: участнику нужно снова открыть бота в личке. Затем ведущий может продолжить через /resume."}})
                return mutation

            self.repository.apply(snapshot.state.game_id, snapshot.version,
                                  f"delivery:{entry['id']}:{snapshot.state.game_id}", transition)

    def deliver_outbox(self, now=None):
        now = now or self.clock()
        delivered = 0
        entries = sorted(self.repository.claim_outbox(limit=50, now=now), key=lambda row: row["id"])
        for entry in entries:
            try:
                try:
                    result = self.bot.call(entry["method"], entry["payload"])
                except BotAPIError as error:
                    if entry["method"] != "sendPhoto" or error.error_code != 400:
                        raise
                    payload = dict(entry["payload"])
                    payload.pop("photo", None)
                    payload["text"] = payload.pop("caption", "Изображение временно недоступно")
                    result = self.bot.call("sendMessage", payload)
                self.repository.mark_sent(entry["id"], result)
                delivered += 1
            except BotAPIError as error:
                code = error.error_code
                if code == 403:
                    try:
                        self._pause_unavailable(entry, now)
                    except StaleAction:
                        # Keep the failed delivery durable until every affected
                        # game has paused, even if no later message is queued.
                        self.repository.retry_outbox(entry["id"], str(code),
                                                     now + timedelta(seconds=1))
                    else:
                        self.repository.fail_outbox(entry["id"], str(code))
                elif code in {0, 429} or code >= 500:
                    seconds = error.retry_after or min(120, 2 ** min(entry["attempts"], 7))
                    self.repository.retry_outbox(entry["id"], str(code), now + timedelta(seconds=seconds))
                else:
                    self.repository.fail_outbox(entry["id"], str(code))
                LOG.warning("Telegram outgoing failure code=%s", code)
        return delivered

    def tick_timers(self, now=None):
        now = now or self.clock()
        count = 0
        for timer in self.repository.due_timers(now=now):
            request = f"timer:{timer['timer_id']}:{timer['expected_version']}"

            def transition(snapshot):
                if timer["kind"] == "idle":
                    mutation = pause_game(snapshot, now)
                else:
                    actor_id = snapshot.state.active_user_id
                    args = {"now": now}
                    if timer["kind"] == "reaction":
                        command_name = "close_reaction"
                    elif timer["kind"] == "help":
                        command_name = "decline_help"
                        actor_id = timer["args"]["helper_id"]
                    elif timer["kind"] == "trade":
                        command_name = "expire_trade"
                        args["trade_id"] = timer["args"]["trade_id"]
                        actor_id = snapshot.state.trades[args["trade_id"]].sender_id
                    elif timer["kind"] == "decision":
                        command_name = "expire_decision"
                        args["decision_id"] = timer["args"]["decision_id"]
                    elif timer["kind"] == "escape":
                        command_name = "expire_escape"
                        for name in ("player_id", "monster_id", "roll_id"):
                            args[name] = timer["args"][name]
                    else:
                        raise RuleError("unknown timer kind")
                    state, events = decide(snapshot.state, Command(snapshot.state.game_id, actor_id,
                                           request, command_name, args), self.release.catalog, snapshot.rng)
                    mutation = Mutation(state, snapshot.rng, events)
                    mutation.activity = timer["kind"] == "reaction"
                metadata = snapshot.metadata if mutation.metadata is None else mutation.metadata
                mutation.messages, mutation.callbacks = self.router.mutation_messages(
                    mutation.state, snapshot.version + 1, metadata, mutation.events, now,
                    status=mutation.status or snapshot.status)
                return mutation

            try:
                result = self.repository.apply(timer["game_id"], timer["expected_version"], request, transition)
                count += not result.duplicate
            except (StaleAction, RuleError):
                self.repository.cancel_timer(timer["timer_id"], timer["expected_version"])
        return count

    def _jobs(self):
        while not self.stop.is_set():
            try:
                self.tick_timers()
                self.deliver_outbox()
            except Exception as error:
                # Error text may contain transport/database secrets or hidden state.
                LOG.error("Background worker failed type=%s", type(error).__name__)
            self.stop.wait(1)

    def run(self):
        with self.repository.singleton("poller") as acquired:
            if not acquired:
                raise RuntimeError("another bot poller owns this database")
            worker = threading.Thread(target=self._jobs, name="delivery-timers", daemon=True)
            worker.start()
            try:
                while not self.stop.is_set():
                    try:
                        updates = self.bot.call("getUpdates", {
                            "offset": self.offset, "timeout": 20,
                            "allowed_updates": ["message", "callback_query", "my_chat_member"]})
                        if not isinstance(updates, list):
                            raise ValueError("invalid updates result")
                        for update in updates:
                            self.handle_update(update)
                        self.repository.set_setting("last_poll_at", self.clock().isoformat())
                    except Exception as error:
                        LOG.error("Polling failed type=%s", type(error).__name__)
                        self.stop.wait(3)
            finally:
                self.stop.set()
                worker.join(timeout=25)


def run_service(config: Config):
    from ..cards.installed import validate_installed_release, load_installed_media
    from ..telegram.router import Router
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(message)s")
    release = validate_installed_release(config.catalog_version)
    media = load_installed_media(release)
    repository = GameRepository(config.database_url,
                                scheduler=lambda s, m: refresh_timers(s, m, datetime.now(timezone.utc)))
    repository.migrate()
    for snapshot in repository.active_games():
        if (snapshot.state.catalog_version, snapshot.state.catalog_digest) != (release.version, release.digest):
            raise ValueError("an active game requires another pinned catalog release")
    bot = BotClient(config.bot_token)
    identity = bot.call("getMe", {})
    if not isinstance(identity, dict) or not identity.get("is_bot") or not identity.get("username"):
        raise ValueError("Telegram identity is not a bot")
    webhook = bot.call("getWebhookInfo", {})
    if isinstance(webhook, dict) and webhook.get("url"):
        bot.call("deleteWebhook", {"drop_pending_updates": False})
    bot.call("setMyCommands", {"commands": [
        {"command": "start", "description": "Открыть личное меню"},
        {"command": "newgame", "description": "Собрать партию в группе"},
        {"command": "game", "description": "Текущая партия"},
        {"command": "pause", "description": "Поставить партию на паузу"},
        {"command": "resume", "description": "Продолжить партию"}]})
    router = Router(repository, release, identity["username"], media=media)
    application = Application(repository, bot, router, release)
    repository.set_setting("release", {"version": release.version, "digest": release.digest,
                                      "bot_username": identity["username"]})
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: application.stop.set())
    LOG.info("Bot started username=%s catalog=%s digest=%s", identity["username"], release.version, release.digest)
    application.run()
