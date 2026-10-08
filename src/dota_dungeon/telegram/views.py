"""Russian player screens separate private hand data from visible profiles."""
from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
from random import Random

from ..core.combat import combat_strength
from ..core.engine import HANDLERS, decide
from ..core.model import Command, GameState


@dataclass(frozen=True)
class Button:
    text: str
    action: str
    args: dict = field(default_factory=dict)
    actor_id: int | None = None
    url: str | None = None


@dataclass
class View:
    destination: str
    text: str
    rows: list[list[Button]] = field(default_factory=list)
    photo: str | None = None


def _nav(label, screen, viewer):
    return Button(label, "nav", {"screen": screen}, viewer)


def card_name(release, card_id):
    presentation = release.presentations.get(card_id)
    return escape(presentation.display_name_ru if presentation else release.catalog[card_id].name)


def _name(user_id, names):
    return escape(names.get(user_id, f"Игрок {user_id}"))


def _main_rows(viewer):
    return [[_nav("Персонаж", "character", viewer), _nav("Рука", "hand", viewer)],
            [_nav("Экипировка", "equipment", viewer), _nav("Стоимость", "prices", viewer)],
            [_nav("Игроки", "players", viewer), _nav("Обмен", "trade", viewer)],
            [_nav("Мои партии", "matches", viewer)]]


def _profile(state, viewer, user_id, release, names, own):
    player = state.players[user_id]
    text = [f"<b>{_name(user_id, names)}</b>", f"Уровень: {player.level}",
            f"Сила: {combat_strength(state, user_id, release.catalog)}"]
    for title, ids in [("Класс", player.role_ids), ("Происхождение", player.race_ids)]:
        text.append(title + ": " + (", ".join(card_name(release, cid) for cid in ids) or "нет"))
    text.append("<b>Надето</b>")
    text.extend(card_name(release, cid) for cid in player.equipped)
    if not player.equipped:
        text.append("Нет предметов")
    carried = [cid for cid in player.in_play if cid not in player.equipped and release.catalog[cid].kind == "item"]
    text.append("<b>Переносимые вещи</b>")
    text.extend(card_name(release, cid) for cid in carried)
    if not carried:
        text.append("Нет вещей")
    persistent = [cid for cid in player.in_play if cid not in set(player.equipped + player.role_ids + player.race_ids + carried)]
    if persistent:
        text.append("<b>Постоянные эффекты</b>")
        text.extend(card_name(release, cid) for cid in persistent)
    if own:
        text.append(f"Карт в руке: {len(player.hand)}")
        for cid in player.role_ids + player.race_ids:
            for ability in release.catalog[cid].abilities:
                cost, limit = ability["cost"], ability["limit"]
                zone = {"hand": "из руки", "in_play": "из выложенных карт", "either": "из руки или выложенных карт"}[cost["zone"]]
                count = f"вся рука, минимум {cost['count']}" if cost.get("mode") == "all_hand" else str(cost["count"])
                scope = {"combat": "за бой", "escape_attempt": "за попытку побега", "turn": "за ход", "unlimited": "без ограничения"}[limit["scope"]]
                text.append(f"<b>{escape(ability['key'])}</b> · Стоимость: {count} карт {zone}. Лимит: {limit.get('max_uses') or '∞'} {scope}.")
    return View(f"user:{viewer}", "\n".join(text), _main_rows(viewer))


def _group(state, viewer, release, names):
    if state.phase == "lobby":
        lines = ["<b>Dota × Манчкин</b>", "Партия на 2–6 игроков. Герой определяется картами в игре."]
        lines.extend(f"{'✅' if state.players[uid].ready else '⏳'} {_name(uid, names)}" for uid in state.order)
        lines.append("Откройте бота в личке, затем нажмите «Готов».")
        return View("group", "\n".join(lines), [
            [Button("Войти", "join"), Button("Готов", "ready", {"ready": True})],
            [Button("Выйти", "leave_lobby"), Button("Начать", "start")],
        ])
    lines = ["<b>Dota × Манчкин</b>"]
    rows = []
    active = state.active_user_id
    if active is not None:
        lines.append("Ход: " + _name(active, names))
    if state.combat:
        combat = state.combat
        lines.append("<b>Бой</b>")
        for cid in combat.monster_ids:
            lines.append(f"{card_name(release, cid)} — сила {release.catalog[cid].bonus}")
        fighter_total = sum(combat_strength(state, uid, release.catalog) for uid in combat.fighter_ids)
        enemy_total = sum(release.catalog[cid].bonus for cid in combat.monster_ids) + combat.monster_strength_bonus
        enemy_total += sum(release.catalog[cid].bonus for cid in combat.modifier_ids)
        lines.append(f"Игроки: {fighter_total} · Противники: {enemy_total}")
        if combat.reaction_deadline:
            lines.append("Окно реакции до " + combat.reaction_deadline.strftime("%H:%M:%S UTC"))
        if state.phase == "combat.active":
            rows.append([Button("Заявить победу", "declare_win", actor_id=active),
                         Button("Бежать", "begin_escape", actor_id=active)])
    elif state.phase == "turn.prepare":
        if getattr(state, "pending_initial_triggers", []):
            lines.append("Подготовка перед первой дверью: разыграйте классы и происхождения из лички. Начальные эффекты разрешатся при открытии первой двери.")
        rows.append([Button("Открыть дверь", "open_door", actor_id=active)])
    elif state.phase == "turn.after_door":
        rows.append([Button("Обыскать комнату", "loot_room", actor_id=active)])
    elif state.phase == "turn.charity":
        rows.append([Button("Завершить ход", "end_turn", actor_id=active)])
    elif state.phase == "game.finished":
        winners = [uid for uid, player in state.players.items() if player.level >= 10]
        lines.append("🏆 Победа: " + ", ".join(_name(uid, names) for uid in winners))
    return View("group", "\n".join(lines), rows)


def _render_view(state: GameState, viewer_id: int, screen: str, release, *, names: dict | None = None) -> View:
    names = names or {}
    if screen == "group":
        return _group(state, viewer_id, release, names)
    if viewer_id not in state.players:
        raise ValueError("not a player in this game")
    player = state.players[viewer_id]
    if screen in ("main", "character"):
        return _profile(state, viewer_id, viewer_id, release, names, True)
    if screen.startswith("profile:"):
        try:
            subject = int(screen.removeprefix("profile:"))
        except ValueError as exc:
            raise ValueError("invalid profile") from exc
        if subject not in state.players:
            raise ValueError("unknown player")
        return _profile(state, viewer_id, subject, release, names, False)
    if screen == "players":
        return View(f"user:{viewer_id}", "<b>Игроки партии</b>", [
            [_nav(names.get(uid, f"Игрок {uid}"), f"profile:{uid}", viewer_id)] for uid in state.order
        ] + [[_nav("Назад", "main", viewer_id)]])
    if screen.startswith("hand"):
        try:
            page = int(screen.partition(":")[2] or "0")
        except ValueError as exc:
            raise ValueError("invalid hand page") from exc
        if page < 0:
            raise ValueError("invalid hand page")
        ids = player.hand[page * 12:(page + 1) * 12]
        lines = [f"<b>Ваша рука · {len(player.hand)} карт</b>"]
        lines.extend(card_name(release, cid) for cid in ids)
        if not ids:
            lines.append("Здесь нет карт")
        rows = [[_nav(release.catalog[cid].name, "card:" + cid, viewer_id)] for cid in ids]
        if page:
            rows.append([_nav("Предыдущие", f"hand:{page - 1}", viewer_id)])
        if len(player.hand) > (page + 1) * 12:
            rows.append([_nav("Следующие", f"hand:{page + 1}", viewer_id)])
        return View(f"user:{viewer_id}", "\n".join(lines), rows + [[_nav("Назад", "main", viewer_id)]])
    if screen == "equipment":
        lines = ["<b>Ваши вещи</b>"]
        rows = []
        for cid in player.in_play:
            card = release.catalog[cid]
            if card.kind != "item":
                continue
            worn = cid in player.equipped
            lines.append(f"{'Надето' if worn else 'Переносится'}: {card_name(release, cid)} · {card.value} золотых")
            action = "unequip" if worn else "equip"
            rows.append([Button(("Снять " if worn else "Надеть ") + card.name, action, {"card_id": cid}, viewer_id)])
        return View(f"user:{viewer_id}", "\n".join(lines), rows + [[_nav("Назад", "main", viewer_id)]])
    if screen == "prices":
        ids = [cid for cid in player.hand + player.in_play if release.catalog[cid].value > 0]
        total = sum(release.catalog[cid].value for cid in ids)
        lines = ["<b>Стоимость вещей</b>"]
        lines.extend(f"{card_name(release, cid)}: {release.catalog[cid].value} золотых" for cid in ids)
        lines.append(f"Общая стоимость вещей: {total} золотых")
        lines.append("Продажа на своём ходу вне боя: полные 1000 золотых за уровень, кроме победного. Сдачи нет.")
        return View(f"user:{viewer_id}", "\n".join(lines), [[_nav("Продать вещи", "sell", viewer_id)], [_nav("Назад", "main", viewer_id)]])
    if screen.startswith("card:"):
        cid = screen.removeprefix("card:")
        if cid not in player.hand + player.in_play:
            raise ValueError("card is not owned")
        card = release.catalog[cid]
        presentation = release.presentations.get(cid)
        lines = [f"<b>{card_name(release, cid)}</b>"]
        if presentation:
            lines.append(escape(presentation.description_ru))
        if card.value:
            lines.append(f"Стоимость: {card.value} золотых")
        if card.bonus:
            lines.append(f"{'Сила противника' if card.kind == 'monster' else 'Бонус'}: {card.bonus:+}")
        if card.slots:
            lines.append("Слот: " + escape(card.slots))
        if card.size == "big":
            lines.append("Крупная вещь")
        rows = [[Button("Сыграть", "choose_card_target", {"card_id": cid}, viewer_id)]]
        if card.kind == "item":
            rows.append([Button("Надеть", "equip", {"card_id": cid}, viewer_id)])
        return View(f"user:{viewer_id}", "\n".join(lines), rows + [[_nav("Назад", "hand", viewer_id)]])
    if screen == "trade":
        rows = [[Button(names.get(uid, f"Игрок {uid}"), "trade_partner", {"partner_id": uid}, viewer_id)]
                for uid in state.order if uid != viewer_id]
        return View(f"user:{viewer_id}", "<b>Обмен вещами</b>\nВыберите партнёра. Обменивать можно только выложенные вещи.",
                    rows + [[_nav("Назад", "main", viewer_id)]])
    raise ValueError("unknown screen")


def legal_action(state, actor, action, args, release, now=None):
    """Ask the core on disposable state/RNG copies; never commit a menu probe."""
    if action not in HANDLERS:
        return False
    now = now or datetime.now(timezone.utc)
    args = deepcopy(args)
    if action in {"declare_win", "play_combat_card", "play_card", "use_ability", "accept_trade", "offer_trade"}:
        args["now"] = now
    if action == "offer_trade":
        args["expires_at"] = now + timedelta(seconds=120)
    try:
        decide(deepcopy(state), Command(state.game_id, actor, "menu-probe", action, args), release.catalog, Random(0))
    except (ValueError, KeyError, TypeError):
        return False
    return True


def _selection(label, flow, data, actor):
    return Button(label, "select", {"flow": flow, **deepcopy(data)}, actor)


def _selected(data, key, eligible):
    ids = data.get(key, [])
    if not isinstance(ids, list) or len(ids) != len(set(ids)) or not set(ids).issubset(eligible):
        raise ValueError("invalid card selection")
    return ids.copy()


def _toggle_rows(ids, selected, data, key, flow, actor, release):
    rows = []
    for cid in ids:
        next_ids = [c for c in selected if c != cid] if cid in selected else selected + [cid]
        rows.append([_selection(("✅ " if cid in selected else "▫️ ") + release.catalog[cid].name,
                                flow, {**data, key: next_ids}, actor)])
    return rows


def _targets(state, actor, rule, release):
    if rule in {"none", "self"}:
        return [("Себя", {"player_id": actor} if rule == "self" else {})]
    if rule == "player":
        return [(f"Игрок {uid}", {"player_id": uid}) for uid in state.order]
    if rule == "monster":
        return [(release.catalog[cid].name, {"monster_id": cid}) for cid in (state.combat.monster_ids if state.combat else [])]
    if rule == "combat":
        if not state.combat:
            return []
        return [(f"Игрок {uid}", {"player_id": uid}) for uid in state.combat.fighter_ids] + [
            (release.catalog[cid].name, {"monster_id": cid}) for cid in state.combat.monster_ids]
    if rule in {"open_item", "identity"}:
        kinds = {"item"} if rule == "open_item" else {"role", "race"}
        return [(f"Игрок {uid}: {release.catalog[cid].name}", {"player_id": uid, "card_id": cid})
                for uid in state.order for cid in state.players[uid].in_play if release.catalog[cid].kind in kinds]
    if rule == "discard":
        return [(release.catalog[cid].name, {"card_id": cid}) for cid in state.door_discard + state.treasure_discard]
    raise ValueError("unknown target rule")


def render_selection(state, viewer, flow, data, release, *, now=None, names=None):
    """Each selection is a fresh actor-scoped intention, never mutable session state."""
    if viewer not in state.players:
        raise ValueError("not a player")
    now = now or datetime.now(timezone.utc)
    player = state.players[viewer]
    data = {k: deepcopy(v) for k, v in data.items() if k != "flow"}
    rows, lines = [], []
    if flow == "sell":
        eligible = [cid for cid in player.hand + player.in_play if release.catalog[cid].kind == "item" and release.catalog[cid].value > 0]
        selected = _selected(data, "selected", eligible)
        total = sum(release.catalog[cid].value for cid in selected)
        lines = ["<b>Продажа вещей</b>", f"Выбрано: {total} золотых · уровней: {total // 1000}", "Сдачи нет. Подтвердите выбранные вещи."]
        rows = _toggle_rows(eligible, selected, data, "selected", flow, viewer, release)
        args = {"card_ids": selected}
        if legal_action(state, viewer, "sell", args, release, now):
            rows.append([Button("Продать выбранные", "sell", args, viewer)])
    elif flow == "charity":
        excess = max(0, len(player.hand) - 5)
        selected = _selected(data, "selected", player.hand)
        if len(selected) > excess:
            raise ValueError("too many charity cards")
        minimum = min(p.level for p in state.players.values())
        recipients = [uid for uid in state.order if state.players[uid].level == minimum and uid != viewer]
        lines = ["<b>Милостыня</b>", f"Лишних карт: {excess}. Выбрано: {len(selected)}."]
        if player.level == minimum:
            lines.append("Вы на минимальном уровне: движок сбросит последние лишние карты руки.")
            args = {"assignments": {}}
        else:
            rows = _toggle_rows(player.hand, selected, data, "selected", flow, viewer, release)
            # The core validates recipient balance and final hand ownership again.
            assignments = {uid: [] for uid in recipients}
            for i, cid in enumerate(selected):
                assignments[recipients[i % len(recipients)]].append(cid)
            args = {"assignments": assignments}
            lines.append("Получатели: " + ", ".join(f"Игрок {uid}" for uid in recipients))
        if legal_action(state, viewer, "give_charity", args, release, now):
            rows.append([Button("Выполнить милостыню", "give_charity", args, viewer)])
    elif flow == "trade":
        partner = data.get("partner_id")
        if partner not in state.players or partner == viewer:
            raise ValueError("invalid partner")
        offered = [cid for cid in player.in_play if release.catalog[cid].kind == "item"]
        requested = [cid for cid in state.players[partner].in_play if release.catalog[cid].kind == "item"]
        offer_ids = _selected(data, "offered_ids", offered)
        request_ids = _selected(data, "requested_ids", requested)
        data.update(partner_id=partner, offered_ids=offer_ids, requested_ids=request_ids)
        lines = [f"<b>Обмен с игроком {partner}</b>", "Вы отдаёте: " + (", ".join(card_name(release, cid) for cid in offer_ids) or "ничего"),
                 "Вы получаете: " + (", ".join(card_name(release, cid) for cid in request_ids) or "ничего"), "Предложение действует 120 секунд."]
        rows = _toggle_rows(offered, offer_ids, data, "offered_ids", flow, viewer, release)
        rows += _toggle_rows(requested, request_ids, data, "requested_ids", flow, viewer, release)
        args = {"partner_id": partner, "offered_ids": offer_ids, "requested_ids": request_ids}
        if legal_action(state, viewer, "offer_trade", args, release, now):
            rows.append([Button("Отправить предложение", "offer_trade", args, viewer)])
    elif flow == "help":
        combat = state.combat
        if not combat or state.active_user_id != viewer or combat.helper_id is not None or combat.pending_help is not None:
            raise ValueError("help unavailable")
        helper = data.get("helper_id")
        lines = ["<b>Условия помощи</b>"]
        if helper is None:
            rows = [[_selection(f"Игрок {uid}", flow, {"helper_id": uid}, viewer)] for uid in state.order if uid != viewer]
        else:
            if helper not in state.players or helper == viewer:
                raise ValueError("invalid helper")
            eligible = [cid for cid in player.in_play if release.catalog[cid].kind == "item"]
            selected = _selected(data, "item_ids", eligible)
            count = data.get("treasure_count", 0)
            available = sum(release.catalog[cid].treasures for cid in combat.monster_ids)
            if type(count) is not int or not 0 <= count <= available:
                raise ValueError("invalid reward")
            data.update(helper_id=helper, treasure_count=count, item_ids=selected)
            lines += [f"Помощник: Игрок {helper}", f"Обещано сокровищ: {count}", "Обещаны вещи: " + (", ".join(card_name(release, cid) for cid in selected) or "нет")]
            rows = [[_selection(f"Сокровищ: {n}", flow, {**data, "treasure_count": n}, viewer)] for n in range(available + 1)]
            rows += _toggle_rows(eligible, selected, data, "item_ids", flow, viewer, release)
            args = {"helper_id": helper, "treasure_count": count, "item_ids": selected}
            if legal_action(state, viewer, "ask_help", args, release, now):
                rows.append([Button("Предложить помощь", "ask_help", args, viewer)])
    elif flow == "play":
        cid = data.get("card_id")
        if cid not in player.hand + player.in_play:
            raise ValueError("card not owned")
        card = release.catalog[cid]
        lines = ["<b>Выберите цель</b>", card_name(release, cid)]
        for label, target in _targets(state, viewer, card.target_rule, release):
            args = {"card_id": cid, "target": target}
            if legal_action(state, viewer, "play_card", args, release, now):
                rows.append([Button(label, "play_card", args, viewer)])
        if card.kind == "monster":
            args = {"card_id": cid}
            if legal_action(state, viewer, "seek_trouble", args, release, now):
                rows.append([Button("Искать неприятности", "seek_trouble", args, viewer)])
        # Small legacy identity fixtures predate declarative play_card metadata.
        elif not card.play_phases:
            action = "play_identity" if card.kind in {"role", "race"} else None
            if action and legal_action(state, viewer, action, {"card_id": cid}, release, now):
                rows.append([Button("Сыграть", action, {"card_id": cid}, viewer)])
    elif flow == "ability":
        key = data.get("ability_key")
        descriptor = next((ability for cid in player.role_ids + player.race_ids for ability in release.catalog[cid].abilities if ability["key"] == key), None)
        if descriptor is None:
            raise ValueError("ability not owned")
        cost = descriptor["cost"]
        eligible = player.hand if cost["zone"] == "hand" else player.in_play if cost["zone"] == "in_play" else player.hand + player.in_play
        selected = _selected(data, "cost_ids", eligible)
        if cost.get("mode") == "all_hand":
            selected = player.hand.copy()
        lines = ["<b>Способность</b>", escape(key), f"Стоимость: {len(selected)} / {cost['count']} карт"]
        if cost.get("mode") != "all_hand":
            rows = _toggle_rows(eligible, selected, {**data, "ability_key": key}, "cost_ids", flow, viewer, release)
        if len(selected) == cost["count"] or cost.get("mode") == "all_hand":
            # Closed target objects are checked by the ability handler before commit.
            targets = [("Без цели", {}), ("Себя", {"player_id": viewer})] + _targets(state, viewer, "player", release)
            if state.combat:
                targets += _targets(state, viewer, "monster", release)
                targets += [(f"Игрок {uid}: {release.catalog[cid].name}", {"player_id": uid, "monster_id": cid})
                            for uid, cid in sorted(state.combat.escape_pending)]
            targets += _targets(state, viewer, "open_item", release)
            for label, target in targets:
                args = {"ability_key": key, "cost_ids": selected, "target": target}
                if legal_action(state, viewer, "use_ability", args, release, now):
                    rows.append([Button("Применить: " + label, "use_ability", args, viewer)])
    else:
        raise ValueError("unknown selection")
    return View(f"user:{viewer}", "\n".join(lines), rows + [[_nav("Отмена", "main", viewer)]])


def _context_rows(state, viewer, release, now):
    rows = []
    combat = state.combat
    if state.phase == "turn.charity" and state.active_user_id == viewer and len(state.players[viewer].hand) > 5:
        rows.append([_selection("Милостыня", "charity", {}, viewer)])
    if combat:
        if state.phase == "combat.active" and state.active_user_id == viewer and combat.helper_id is None and combat.pending_help is None:
            rows.append([_selection("Позвать помощника", "help", {}, viewer)])
        if combat.pending_help and combat.pending_help[0] == viewer:
            rows.append([Button("Принять помощь", "accept_help", {}, viewer), Button("Отклонить помощь", "decline_help", {}, viewer)])
        if combat.reaction_deadline and viewer != state.active_user_id:
            rows.append([Button("Пас", "pass_reaction", {}, viewer)])
        for uid, cid in sorted(combat.escape_pending):
            if uid == viewer:
                rows.append([Button("Бежать от " + release.catalog[cid].name, "run_away", {"monster_id": cid}, viewer)])
    if state.corpse:
        rows.append([_nav("Добыча погибших", "corpses", viewer)])
    for cid in state.players[viewer].role_ids + state.players[viewer].race_ids:
        for ability in release.catalog[cid].abilities if "use_ability" in HANDLERS else []:
            if state.phase in ability.get("phases", []):
                rows.append([_selection("Способность: " + ability["key"], "ability", {"ability_key": ability["key"]}, viewer)])
    return rows


def render_view(state: GameState, viewer_id: int, screen: str, release, *, names=None, now=None) -> View:
    now = now or datetime.now(timezone.utc)
    if screen in {"sell", "charity", "help"}:
        return render_selection(state, viewer_id, screen, {}, release, now=now, names=names)
    if screen == "corpses":
        if viewer_id not in state.players:
            raise ValueError("not a player")
        rows, lines = [], ["<b>Добыча погибших</b>"]
        for deceased, ids in state.corpse.items():
            if deceased == viewer_id or viewer_id in state.corpse_looted_by.get(deceased, set()):
                continue
            hidden = state.corpse_hand.get(deceased, set())
            for cid in ids:
                if cid not in hidden:
                    lines.append(card_name(release, cid))
                    rows.append([Button(release.catalog[cid].name, "loot_corpse", {"deceased_id": deceased, "card_id": cid}, viewer_id)])
            if hidden:
                rows.append([Button("Взять закрытую карту", "loot_hidden_corpse", {"deceased_id": deceased}, viewer_id)])
        return View(f"user:{viewer_id}", "\n".join(lines), rows + [[_nav("Назад", "main", viewer_id)]])
    view = _render_view(state, viewer_id, screen, release, names=names)
    if screen.startswith("card:"):
        cid = screen.removeprefix("card:")
        options = render_selection(state, viewer_id, "play", {"card_id": cid}, release, now=now)
        can_play = any(b.action in HANDLERS for row in options.rows for b in row)
        if not can_play:
            view.rows = [[b for b in row if b.action != "choose_card_target"] for row in view.rows]
    if screen == "trade" and (state.combat is not None or state.phase in {"lobby", "game.finished"}):
        view.rows = [[b for b in row if b.action != "trade_partner"] for row in view.rows]
    if screen in {"main", "character"}:
        view.rows = _context_rows(state, viewer_id, release, now) + view.rows
        combat = state.combat
        if combat and combat.pending_help and combat.pending_help[0] == viewer_id:
            _, count, ids = combat.pending_help
            view.text += f"\n<b>Предложена помощь</b>\nСокровищ: {count}\nВещи: " + (", ".join(card_name(release, cid) for cid in ids) or "нет")
        for trade in state.trades.values():
            if trade.status == "pending" and now < trade.expires_at and viewer_id in {trade.sender_id, trade.receiver_id}:
                view.text += "\n<b>Предложение обмена</b>\nОтдаёт отправитель: " + (", ".join(card_name(release, cid) for cid in trade.offered_ids) or "ничего")
                view.text += "\nОтдаёт получатель: " + (", ".join(card_name(release, cid) for cid in trade.requested_ids) or "ничего")
                if trade.receiver_id == viewer_id:
                    view.rows.insert(0, [Button("Принять обмен", "accept_trade", {"trade_id": trade.id}, viewer_id)])
                view.rows.insert(0, [Button("Отклонить / отменить обмен", "cancel_trade", {"trade_id": trade.id}, viewer_id)])
    if screen == "group" and state.combat:
        for uid in state.order:
            for row in _context_rows(state, uid, release, now):
                public = [b for b in row if b.action in {"run_away", "pass_reaction"}]
                if public:
                    view.rows.append(public)
    if screen != "group" or state.phase != "lobby":
        view.rows = [[b for b in row if b.action in {"nav", "select", "choose_card_target", "trade_partner", "loot_hidden_corpse"}
                      or legal_action(state, b.actor_id, b.action, b.args, release, now)] for row in view.rows]
        view.rows = [row for row in view.rows if row]
    return view
