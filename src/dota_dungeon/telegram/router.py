"""Authorize Telegram identities and durably queue engine results and screens."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from random import Random
from uuid import uuid4

from ..core.engine import decide
from ..core.model import Command
from ..core.setup import new_lobby
from ..service.store import Mutation, Snapshot
from ..service.timers import finish_game, pause_game, resume_game
from .callbacks import CallbackIntent, authorize_callback, new_token
from .views import Button, decision_options, render_endgame_confirmation, render_selection, render_view


class Router:
    def __init__(self, repository, release, bot_username: str, media=None, *, control=None):
        self.repository = repository
        self.release = release
        self.bot_username = bot_username.lstrip("@").lower()
        self.media = media
        self.control = control

    def _message(self, chat_id, text):
        return {"method": "sendMessage", "payload": {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}}

    def _ack(self, query_id, text=None):
        payload = {"callback_query_id": query_id}
        if text:
            payload.update(text=text, show_alert=True)
        return {"method": "answerCallbackQuery", "payload": payload}

    def _render(self, snapshot, viewer, screen, now):
        self._check_release(snapshot.state)
        names = {int(uid): name for uid, name in snapshot.metadata.get("names", {}).items()}
        view = render_view(snapshot.state, viewer, screen, self.release, names=names, now=now,
                           ended_by=snapshot.metadata.get("ended_by"))
        if snapshot.state.phase == "game.finished":
            return view
        if snapshot.status == "paused":
            view.text += "\n⏸ Партия на паузе. Ведущий может продолжить её командой /resume."
            view.rows = [[b for b in row if b.action == "nav"] for row in view.rows]
            view.rows = [row for row in view.rows if row]
        if screen == "group":
            if snapshot.state.phase == "lobby" and snapshot.status == "active":
                view.text += f"\nОкно реакции: {snapshot.metadata.get('reaction_seconds', 30)} секунд."
                view.rows.append([Button(f"{n} сек", "reaction_seconds", {"seconds": n}, snapshot.state.host_id) for n in (15, 30, 60)])
            elif snapshot.state.phase != "game.finished":
                action = "resume" if snapshot.status == "paused" else "pause"
                view.rows.append([Button("Продолжить" if action == "resume" else "Пауза", action, {}, snapshot.state.host_id)])
        if screen.startswith("card:"):
            view.photo = self._photo(screen.removeprefix("card:"))
        return view

    def _photo(self, card_id):
        if hasattr(self.media, "image_for"):
            return self.media.image_for(card_id) if self.media.catalog_digest == self.release.digest else None
        if not self.media or self.media.get("catalog_version") != self.release.version or self.media.get("catalog_digest") != self.release.digest:
            return None
        card = self.release.catalog.get(card_id)
        if card is None:
            return None
        asset = self.media.get("assets", {}).get(self.media.get("bindings", {}).get(card.rule_key), {})
        url = asset.get("image_url", "")
        return url if asset.get("status") == "verified" and url.startswith("https://") else None

    def _check_release(self, state):
        if (state.catalog_version, state.catalog_digest) != (self.release.version, self.release.digest):
            raise ValueError("game requires its pinned catalog")

    def outgoing_view(self, snapshot, view, now):
        """Build a single audience's message and immutable server intentions."""
        state = snapshot.state
        chat = state.group_id if view.destination == "group" else self.repository.private_chat(int(view.destination.split(":")[1]))
        if chat is None:
            return [], []
        callbacks, rows = [], []
        for row in view.rows:
            buttons = []
            for button in row:
                if button.url:
                    buttons.append({"text": button.text, "url": button.url})
                else:
                    expires_at = now + timedelta(seconds=120)
                    if button.action not in {"nav", "pause", "resume", "confirm_endgame", "cancel_endgame", "reaction_seconds"}:
                        decision = decision_options(state, button.actor_id, self.release.catalog)
                        if decision:
                            if not decision["mandatory"]:
                                expires_at = min(expires_at, datetime.fromisoformat(decision["deadline"]))
                        elif state.combat and state.combat.escape_deadline:
                            expires_at = min(expires_at, state.combat.escape_deadline)
                    intent = CallbackIntent(new_token(), state.game_id, snapshot.version, button.actor_id,
                                            chat, button.action, deepcopy(button.args), expires_at)
                    callbacks.append(intent)
                    buttons.append({"text": button.text, "callback_data": intent.token})
            if buttons:
                rows.append(buttons)
        payload = {"chat_id": chat, "parse_mode": "HTML"}
        method = "sendMessage"
        if view.photo:
            method = "sendPhoto"
            payload.update(photo=view.photo, caption=view.text if len(view.text) <= 1024 else "Карточка")
        else:
            payload["text"] = view.text
        if rows:
            payload["reply_markup"] = {"inline_keyboard": rows}
        messages = [{"method": method, "payload": payload}]
        if view.photo and len(view.text) > 1024:
            payload.pop("reply_markup", None)
            detail = self._message(chat, view.text)
            if rows:
                detail["payload"]["reply_markup"] = {"inline_keyboard": rows}
            messages.append(detail)
        return messages, callbacks

    def _panel(self, snapshot, viewer, screen, now):
        view = self._render(snapshot, viewer, screen, now)
        messages, callbacks = self.outgoing_view(snapshot, view, now)
        if screen == "group" and snapshot.state.phase == "lobby":
            intent = CallbackIntent(new_token(), snapshot.state.game_id, snapshot.version, None,
                                    snapshot.state.group_id, "link_private", {}, now + timedelta(seconds=120))
            callbacks.append(intent)
            messages[0]["payload"]["reply_markup"]["inline_keyboard"].append([
                {"text": "Открыть личку", "url": f"https://t.me/{self.bot_username}?start={intent.token}"}])
        return messages, callbacks

    def _matches(self, uid, now, *, chat_override=None):
        snapshots = self.repository.active_user(uid)
        messages, callbacks = [], []
        chat = chat_override if chat_override is not None else self.repository.private_chat(uid)
        if not snapshots:
            return [self._message(chat, "Активных партий нет. Создайте партию в группе командой /newgame.")], []
        rows = []
        for snapshot in snapshots:
            state = snapshot.state
            intent = CallbackIntent(new_token(), state.game_id, snapshot.version, uid, chat,
                                    "nav", {"screen": "main"}, now + timedelta(seconds=120))
            callbacks.append(intent)
            rows.append([{"text": f"Партия в группе {state.group_id}", "callback_data": intent.token}])
        result = self._message(chat, "<b>Ваши партии</b>\nВыберите группу.")
        result["payload"]["reply_markup"] = {"inline_keyboard": rows}
        messages.append(result)
        return messages, callbacks

    def _events(self, state, events, actor):
        """Render only each event's declared audience; unknown events expose no data."""
        messages = []
        labels = {"player.joined": "Игрок вошёл в партию.", "player.ready": "Готовность обновлена.",
                  "game.started": "Партия началась!", "room.looted": "Комната обыскана.",
                  "combat.started": "Начался бой.", "combat.won": "Бой выигран.",
                  "game.won": "🏆 Победа!", "game.ended": "Ведущий завершил партию без победителя.",
                  "escape.rolled": "Бросок на побег.",
                  "escape.rerolled": "Кубик побега переброшен.", "die.rolled": "Бросок кубика.",
                  "decision.required": "Требуется выбор.", "curse.immune": "Проклятие отражено.",
                  "treasure.drawn": "Получено сокровище.", "elf.helper_levels": "Помощник получил уровень.",
                  "player.died": "Игрок погиб.", "trade.accepted": "Обмен завершён.",
                  "help.accepted": "Помощник вступил в бой.", "charity.given": "Лишние карты переданы.",
                  "charity.discarded": "Лишние карты сброшены.", "turn.started": "Начался новый ход."}
        from .views import card_name
        for event in events:
            if event.audience == "group":
                destination = state.group_id
            elif event.audience == "actor":
                destination = self.repository.private_chat(actor)
            elif event.audience.startswith("user:"):
                destination = self.repository.private_chat(int(event.audience.split(":")[1]))
            else:
                continue
            if destination is None:
                continue
            text = labels.get(event.name, "Состояние партии обновлено.")
            if event.name == "decision.required":
                from .views import DECISION_LABELS
                text = DECISION_LABELS.get(event.data.get("kind"), "Требуется выбор") + "."
                text += "\nВыбор в личке: " + ", ".join(f"Игрок {u}" for u in event.data.get("chooser_ids", []))
            if event.name in {"escape.rolled", "escape.rerolled", "die.rolled"} and type(event.data.get("die")) is int:
                text += f"\nРезультат: {event.data['die']}"
            if event.name == "player.died":
                text += "\nОткрытая добыча:\n" + "\n".join(card_name(self.release, cid) for cid in event.data.get("card_ids", []) if cid in self.release.catalog)
            # Only public disclosure events may render actual card identities in a group.
            if event.name in {"door.revealed", "item.equipped", "item.unequipped", "identity.played", "combat.card_played", "card.played", "curse.applied"}:
                cid = event.data.get("card_id")
                if cid in self.release.catalog:
                    text += "\n" + card_name(self.release, cid)
            if event.name in {"hand.dealt", "card.drawn", "treasure.drawn"}:
                ids = event.data.get("card_ids", [event.data.get("card_id")])
                text = "Получены карты:\n" + "\n".join(card_name(self.release, cid) for cid in ids if cid in self.release.catalog)
            outgoing = self._message(destination, text)
            if event.name == "door.revealed":
                photo = self._photo(event.data.get("card_id"))
                if photo:
                    outgoing = {"method": "sendPhoto", "payload": {"chat_id": destination, "photo": photo, "caption": text, "parse_mode": "HTML"}}
            messages.append(outgoing)
        return messages

    def mutation_messages(self, state, version, metadata, events, now, *, actor_id=None, status="active"):
        """Render a committed transition for actions and durable timer workers."""
        snapshot = Snapshot(state, Random(0), version, metadata, status)
        actor_id = actor_id if actor_id is not None else state.active_user_id
        messages = self._events(state, events, actor_id)
        callbacks = []
        for viewer, screen in [(actor_id, "group")] + [(uid, "main") for uid in state.order]:
            outgoing, intentions = self._panel(snapshot, viewer, screen, now)
            messages.extend(outgoing)
            callbacks.extend(intentions)
        return messages, callbacks

    def _control(self, snapshot, actor, action, args, update_id, now, query_id=None):
        if actor != snapshot.state.host_id:
            raise ValueError("only host may control game")
        def transition(saved):
            if action == "reaction_seconds":
                seconds = args.get("seconds")
                if saved.state.phase != "lobby" or type(seconds) is not int or seconds not in {15, 30, 60}:
                    raise ValueError("invalid reaction configuration")
                metadata = deepcopy(saved.metadata)
                metadata["reaction_seconds"] = seconds
                mutation = Mutation(saved.state, saved.rng, [], metadata=metadata)
            else:
                mutation = pause_game(saved, now) if action == "pause" else resume_game(saved, now)
            messages, callbacks = self.mutation_messages(mutation.state, saved.version + 1,
                mutation.metadata or saved.metadata, [], now, actor_id=actor, status=mutation.status or saved.status)
            mutation.messages = ([self._ack(query_id)] if query_id else []) + messages
            mutation.callbacks = callbacks
            return mutation
        self.repository.apply(snapshot.state.game_id, snapshot.version, update_id, transition, allow_paused=action == "resume")

    def _finish(self, snapshot, actor, update_id, now, query_id):
        def transition(saved):
            mutation = finish_game(saved, actor, now)
            messages, callbacks = self.mutation_messages(mutation.state, saved.version + 1,
                mutation.metadata, mutation.events, now, actor_id=actor, status=mutation.status)
            mutation.messages = [self._ack(query_id)] + messages
            mutation.callbacks = callbacks
            return mutation
        self.repository.apply(snapshot.state.game_id, snapshot.version, update_id, transition, allow_paused=True)

    def route_update(self, update: dict, *, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if now.utcoffset() is None:
            raise ValueError("trusted time requires timezone")
        update_id = "telegram:" + str(update["update_id"])
        if self.repository.update_seen(update_id):
            return
        query = update.get("callback_query")
        if query:
            try:
                self._callback(query, update_id, now)
            except (ValueError, KeyError, TypeError):
                self.repository.enqueue(update_id, [self._ack(query["id"], "Кнопка недоступна или устарела. Откройте /game заново.")])
            return
        incoming = update.get("message")
        if not incoming:
            self.repository.enqueue(update_id, [])
            return
        try:
            self._command(incoming, update_id, now)
        except (ValueError, KeyError, TypeError):
            self.repository.enqueue(update_id, [self._message(incoming["chat"]["id"], "Действие недоступно. Откройте /game заново.")])

    def _command(self, incoming, update_id, now):
        uid, chat = incoming["from"]["id"], incoming["chat"]["id"]
        if type(uid) is not int or type(chat) is not int:
            raise ValueError("invalid Telegram identity")
        text = incoming.get("text", "").split()
        if not text or not text[0].startswith("/"):
            self.repository.enqueue(update_id, [])
            return
        name, _, addressed = text[0][1:].partition("@")
        if addressed and addressed.lower() != self.bot_username:
            self.repository.enqueue(update_id, [])
            return
        private = incoming["chat"]["type"] == "private"
        if name == "endgame":
            if incoming["chat"]["type"] not in {"group", "supergroup"}:
                raise ValueError("ending must be requested in a group")
            snapshot = self.repository.active_group(chat)
            if snapshot is None or uid != snapshot.state.host_id or snapshot.status not in {"active", "paused"}:
                raise ValueError("only host can request ending an active game")
            self._check_release(snapshot.state)
            view = render_endgame_confirmation(snapshot.state, uid)
            messages, callbacks = self.outgoing_view(snapshot, view, now)
            self.repository.enqueue(update_id, messages, callbacks=callbacks, game_id=snapshot.state.game_id)
            return
        if name == "start" and private:
            if uid != chat:
                raise ValueError("invalid private identity")
            invalid_link = False
            if len(text) > 1:
                intent = self.repository.callback(text[1])
                if intent is None or intent.action != "link_private" or now >= intent.expires_at:
                    invalid_link = True
                else:
                    snapshot = self.repository.get(intent.game_id)
                    invalid_link = snapshot.state.group_id != intent.chat_id or snapshot.version != intent.expected_version
            messages, callbacks = self._matches(uid, now, chat_override=chat)
            if invalid_link:
                messages.insert(0, self._message(chat, "Ссылка лобби устарела. Личка подключена; обновите /game в группе."))
            self.repository.enqueue(update_id, messages, callbacks=callbacks, private_link=(uid, chat))
            return
        if name == "newgame" and incoming["chat"]["type"] in {"group", "supergroup"}:
            if self.repository.active_group(chat):
                self.repository.enqueue(update_id, [self._message(chat, "В этой группе уже есть партия. Откройте /game.")])
                return
            state = new_lobby(uuid4().hex, chat, uid, self.release.catalog)
            state.catalog_version, state.catalog_digest = self.release.version, self.release.digest
            rng = Random()
            state, _ = decide(state, Command(state.game_id, uid, update_id, "join"), self.release.catalog, rng)
            metadata = {"names": {str(uid): incoming["from"].get("first_name", str(uid))}, "reaction_seconds": 30}
            snapshot = Snapshot(state, rng, 0, metadata)
            messages, callbacks = self._panel(snapshot, uid, "group", now)
            self.repository.create(state, rng, metadata, update_id=update_id, messages=messages, callbacks=callbacks)
            return
        if private:
            if self.repository.private_chat(uid) != chat:
                self.repository.enqueue(update_id, [self._message(chat, "Сначала откройте личку командой /start.")])
                return
            matches = self.repository.active_user(uid)
            if name in {"games", "start"} or len(matches) != 1:
                messages, callbacks = self._matches(uid, now)
            else:
                screen = {"game": "main", "hand": "hand", "character": "character", "equipment": "equipment",
                          "prices": "prices", "players": "players", "trade": "trade"}.get(name)
                if screen is None:
                    self.repository.enqueue(update_id, [])
                    return
                messages, callbacks = self._panel(matches[0], uid, screen, now)
            self.repository.enqueue(update_id, messages, callbacks=callbacks)
            return
        snapshot = self.repository.active_group(chat)
        if snapshot and name in {"pause", "resume"}:
            self._control(snapshot, uid, name, {}, update_id, now)
            return
        if snapshot and name == "game":
            messages, callbacks = self._panel(snapshot, uid, "group", now)
            self.repository.enqueue(update_id, messages, callbacks=callbacks, game_id=snapshot.state.game_id)
        else:
            self.repository.enqueue(update_id, [])

    def _callback(self, query, update_id, now):
        uid, chat = query["from"]["id"], query["message"]["chat"]["id"]
        intent = self.repository.callback(query["data"])
        if intent is None:
            raise ValueError("unknown button")
        snapshot = self.repository.get(intent.game_id)
        state = snapshot.state
        self._check_release(state)
        authorize_callback(intent, telegram_user_id=uid, chat_id=chat, now=now, current_version=snapshot.version,
                           member_ids=set(state.players), phase=state.phase, host_id=state.host_id)
        chat_type = query["message"]["chat"].get("type")
        if intent.chat_id == state.group_id:
            if chat_type not in {"group", "supergroup"}:
                raise ValueError("group callback requires a group chat")
        elif intent.chat_id != self.repository.private_chat(uid) or chat_type != "private":
            raise ValueError("private callback requires the linked private chat")
        if intent.action in {"confirm_endgame", "cancel_endgame"}:
            if (uid != state.host_id or chat != state.group_id
                    or query["message"]["chat"].get("type") not in {"group", "supergroup"}
                    or snapshot.status not in {"active", "paused"} or state.phase == "game.finished"):
                raise ValueError("only current host in the game group may end or cancel")
            if intent.action == "confirm_endgame":
                self._finish(snapshot, uid, update_id, now, query["id"])
            else:
                messages, callbacks = self._panel(snapshot, uid, "group", now)
                self.repository.enqueue(update_id, [self._ack(query["id"])] + messages,
                                        callbacks=callbacks, game_id=state.game_id)
            return
        if snapshot.status == "finished" and intent.action != "nav":
            raise ValueError("game finished")
        if intent.action in {"pause", "resume", "reaction_seconds"}:
            self._control(snapshot, uid, intent.action, intent.args, update_id, now, query["id"])
            return
        if intent.action in {"select", "choose_card_target", "trade_partner"}:
            if snapshot.status != "active":
                raise ValueError("game paused")
            if chat != self.repository.private_chat(uid):
                raise ValueError("selection must be private")
            if intent.action == "select":
                flow, data = intent.args["flow"], intent.args
            elif intent.action == "choose_card_target":
                flow, data = "play", intent.args
            else:
                flow, data = "trade", intent.args
            view = render_selection(state, uid, flow, data, self.release, now=now)
            messages, callbacks = self.outgoing_view(snapshot, view, now)
            self.repository.enqueue(update_id, [self._ack(query["id"])] + messages, callbacks=callbacks, game_id=state.game_id)
            return
        if intent.action == "nav":
            if chat != self.repository.private_chat(uid):
                raise ValueError("private link unavailable")
            if intent.args["screen"] == "matches":
                messages, callbacks = self._matches(uid, now)
                outgoing_game_id = None
            else:
                messages, callbacks = self._panel(snapshot, uid, intent.args["screen"], now)
                outgoing_game_id = state.game_id
            self.repository.enqueue(update_id, [self._ack(query["id"])] + messages, callbacks=callbacks, game_id=outgoing_game_id)
            return
        if intent.action == "ready" and intent.args.get("ready"):
            if self.repository.private_chat(uid) is None:
                self.repository.enqueue(update_id, [self._ack(query["id"], "Откройте личку бота: /start."),
                    self._message(state.group_id, "Для готовности откройте личку бота командой /start.")], game_id=state.game_id)
                return
        if intent.action == "start" and any(self.repository.private_chat(pid) is None for pid in state.order):
            raise ValueError("private delivery unavailable")

        def transition(saved):
            args = deepcopy(intent.args)
            action = intent.action
            args["now"] = now
            args["reaction_seconds"] = saved.metadata.get("reaction_seconds", 30)
            if intent.action == "declare_win":
                args["seconds"] = saved.metadata.get("reaction_seconds", 30)
            if intent.action == "offer_trade":
                args["expires_at"] = now + timedelta(seconds=120)
            if intent.action == "give_charity":
                args["assignments"] = {int(k): v for k, v in args["assignments"].items()}
            result, events = decide(saved.state, Command(state.game_id, uid, update_id, action, args),
                                    self.release.catalog, saved.rng)
            metadata = deepcopy(saved.metadata)
            if intent.action == "join":
                metadata.setdefault("names", {})[str(uid)] = query["from"].get("first_name", f"Игрок {uid}")
            next_snapshot = Snapshot(result, saved.rng, saved.version + 1, metadata, saved.status)
            messages, callbacks = self.mutation_messages(result, next_snapshot.version, metadata, events, now, actor_id=uid, status=saved.status)
            messages.insert(0, self._ack(query["id"]))
            mutation = Mutation(result, saved.rng, events, messages=messages, metadata=metadata, callbacks=callbacks)
            return mutation

        self.repository.apply(state.game_id, intent.expected_version, update_id, transition)


def route_update(update, repository, bot=None, now=None, *, release=None, bot_username=None, router=None):
    """Compatibility entry point; runtime normally retains one Router instance."""
    if router is None:
        router = Router(repository, release, bot_username)
    return router.route_update(update, now=now)
