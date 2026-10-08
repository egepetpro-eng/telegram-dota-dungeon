"""Russian player screens separate private hand data from visible profiles."""
from dataclasses import dataclass, field
from html import escape

from ..core.combat import combat_strength
from ..core.model import GameState


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
        rows.append([Button("Открыть дверь", "open_door", actor_id=active)])
    elif state.phase == "turn.after_door":
        rows.append([Button("Обыскать комнату", "loot_room", actor_id=active)])
    elif state.phase == "turn.charity":
        rows.append([Button("Завершить ход", "end_turn", actor_id=active)])
    elif state.phase == "game.finished":
        winners = [uid for uid, player in state.players.items() if player.level >= 10]
        lines.append("🏆 Победа: " + ", ".join(_name(uid, names) for uid in winners))
    return View("group", "\n".join(lines), rows)


def render_view(state: GameState, viewer_id: int, screen: str, release, *, names: dict | None = None) -> View:
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
