"""Russian player screens separate private hand data from visible profiles."""
from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
from random import Random
from itertools import combinations

from ..core.combat import combat_strength, combat_totals
from ..core.character import effective_hand_limit
from ..core.items import is_item_card, ignored_item
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


ABILITY_LABELS = {
    "warrior_berserk": "Берсерк", "thief_backstab": "Удар в спину",
    "thief_theft": "Кража", "wizard_flight": "Полёт", "wizard_charm": "Укрощение",
    "cleric_resurrection": "Воскрешение", "cleric_turn_undead": "Изгнание нежити",
    "halfling_escape_retry": "Повторить побег", "hireling_escape": "Пожертвовать наёмником",
    "rat_on_a_stick_escape": "Пожертвовать крысой",
}


def _price(card):
    return f"{card.value} золотых" if card.value else "Нет стоимости"


def _ability_sources(player, release):
    seen = set()
    for cid in dict.fromkeys(player.role_ids + player.race_ids + player.in_play):
        for descriptor in release.catalog[cid].abilities:
            if descriptor["key"] not in seen:
                seen.add(descriptor["key"])
                yield cid, descriptor


def _ability_label(source, descriptor, release):
    return card_name(release, source) + " · " + ABILITY_LABELS.get(descriptor["key"], "Способность")


def _ability_cost_text(ability):
    cost, limit = ability["cost"], ability["limit"]
    zone = {"hand": "из руки", "in_play": "из выложенных карт", "either": "из руки или выложенных карт"}[cost["zone"]]
    count = f"вся рука, минимум {cost['count']}" if cost.get("mode") == "all_hand" else str(cost["count"])
    scope = {"combat": "за бой", "escape_attempt": "за попытку побега", "turn": "за ход", "unlimited": "без ограничения"}[limit["scope"]]
    return f"Стоимость: {count} карт {zone}. Лимит: {limit.get('max_uses') or '∞'} {scope}."


def _ability_targets(state, actor, key, release):
    if key in {"warrior_berserk", "cleric_turn_undead"}:
        return [("Применить", {})]
    if key == "thief_backstab":
        return _targets(state, actor, "player", release)
    if key == "thief_theft":
        return _targets(state, actor, "open_item", release)
    if key == "cleric_resurrection":
        # Simultaneous reward replacements are integrated with Task6 decisions.
        return [("Воскресить верхнюю дверь", {"deck": "door"})]
    if key in {"wizard_charm", "wizard_flight", "halfling_escape_retry", "hireling_escape", "rat_on_a_stick_escape"}:
        return _targets(state, actor, "monster", release)
    return []


def _ability_costs(state, actor, source, descriptor, release):
    player, cost = state.players[actor], descriptor["cost"]
    if descriptor["key"] in {"hireling_escape", "rat_on_a_stick_escape"}:
        return [source]
    ids = player.hand if cost["zone"] == "hand" else player.in_play if cost["zone"] == "in_play" else player.hand + player.in_play
    return [cid for cid in ids if (actor, cid) not in state.pending_initial_triggers
            and not (cid in player.in_play and (cid == source or release.catalog[cid].kind == "curse"))]


def _ability_available(state, actor, source, descriptor, release, now):
    if state.phase not in descriptor.get("phases", []):
        return False
    eligible = _ability_costs(state, actor, source, descriptor, release)
    selections = [state.players[actor].hand] if descriptor["cost"].get("mode") == "all_hand" else combinations(eligible, descriptor["cost"]["count"])
    for costs in selections:
        for _, target in _ability_targets(state, actor, descriptor["key"], release):
            if legal_action(state, actor, "use_ability", {"ability_key": descriptor["key"], "cost_ids": list(costs), "target": target}, release, now):
                return True
    return False


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
    text.append("Пол персонажа: " + {"male": "мужской", "female": "женский", None: "не выбран"}[player.character_sex])
    text.append("<b>Надето</b>")
    text.extend(card_name(release, cid) for cid in player.equipped)
    if not player.equipped:
        text.append("Нет предметов")
    assigned = set(player.hireling_items.values())
    if assigned:
        text.append("<b>Вещи наёмника</b>")
        text.extend(card_name(release, cid) for cid in assigned)
    carried = [cid for cid in player.in_play if cid not in set(player.equipped) | assigned and is_item_card(release.catalog[cid])]
    text.append("<b>Переносимые вещи</b>")
    text.extend(card_name(release, cid) for cid in carried)
    if not carried:
        text.append("Нет вещей")
    persistent = [cid for cid in player.in_play if cid not in set(player.equipped + player.role_ids + player.race_ids + carried) | assigned]
    if persistent:
        text.append("<b>Постоянные эффекты</b>")
        text.extend(card_name(release, cid) for cid in persistent)
    if own:
        text.append(f"Карт в руке: {len(player.hand)}")
        text.append(f"Лимит руки: {effective_hand_limit(state, user_id, release.catalog)}")
        for cid, ability in _ability_sources(player, release):
            text.append(f"<b>{_ability_label(cid, ability, release)}</b> · {_ability_cost_text(ability)}")
    for attachment, item in player.attachments.items():
        text.append(card_name(release, attachment) + " → " + card_name(release, item))
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
        fighter_total, enemy_total = combat_totals(state, release.catalog)
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
            if not is_item_card(card):
                continue
            worn = cid in player.equipped
            status = "У наёмника" if cid in player.hireling_items.values() else "Надето" if worn else "Переносится"
            lines.append(f"{status}: {card_name(release, cid)} · {_price(card)}")
            rows.append([_nav(card.name, "card:" + cid, viewer_id)])
            action = "unequip" if worn else "equip"
            rows.append([Button(("Снять " if worn else "Надеть ") + card.name, action, {"card_id": cid}, viewer_id)])
        for cid in player.in_play:
            if release.catalog[cid].rule_key == "hireling":
                rows.append([_selection("Назначить вещь: " + card_name(release, cid), "hireling", {"hireling_id": cid}, viewer_id)])
        return View(f"user:{viewer_id}", "\n".join(lines), rows + [[_nav("Назад", "main", viewer_id)]])
    if screen == "prices":
        ids = [cid for cid in player.hand + player.in_play if is_item_card(release.catalog[cid])]
        total = sum(release.catalog[cid].value for cid in ids)
        lines = ["<b>Стоимость вещей</b>"]
        lines.extend(f"{card_name(release, cid)}: {_price(release.catalog[cid])}" for cid in ids)
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
        if is_item_card(card):
            lines.append(f"Стоимость: {_price(card)}")
        if card.bonus:
            lines.append(f"{'Сила противника' if card.kind == 'monster' else 'Бонус'}: {card.bonus:+}")
        if card.slots:
            lines.append("Слот: " + escape(card.slots))
        if card.size == "big":
            lines.append("Крупная вещь")
        rows = [[Button("Сыграть", "choose_card_target", {"card_id": cid}, viewer_id)]]
        if is_item_card(card):
            rows.append([Button("Выложить вещь", "carry_item", {"card_id": cid}, viewer_id)])
            rows.append([Button("Надеть", "equip", {"card_id": cid}, viewer_id)])
        rows.append([Button("Сбросить класс / происхождение", "discard_identity", {"card_id": cid}, viewer_id)])
        return View(f"user:{viewer_id}", "\n".join(lines), rows + [[_nav("Назад", "hand", viewer_id)]])
    if screen == "trade":
        rows = [[Button(names.get(uid, f"Игрок {uid}"), "trade_partner", {"partner_id": uid}, viewer_id)]
                for uid in state.order if uid != viewer_id]
        return View(f"user:{viewer_id}", "<b>Обмен вещами</b>\nВыберите партнёра. Обменивать можно только выложенные вещи.",
                    rows + [[_nav("Назад", "main", viewer_id)]])
    raise ValueError("unknown screen")


def _action_result(state, actor, action, args, release, now=None):
    """Ask the core on disposable state/RNG copies; never commit a menu probe."""
    if action not in HANDLERS:
        return None
    now = now or datetime.now(timezone.utc)
    args = deepcopy(args)
    if action in {"declare_win", "play_combat_card", "play_card", "use_ability", "accept_trade", "offer_trade"}:
        args["now"] = now
    if action == "offer_trade":
        args["expires_at"] = now + timedelta(seconds=120)
    try:
        result, _ = decide(deepcopy(state), Command(state.game_id, actor, "menu-probe", action, args), release.catalog, Random(0))
    except (ValueError, KeyError, TypeError):
        return None
    return result


def legal_action(state, actor, action, args, release, now=None):
    return _action_result(state, actor, action, args, release, now) is not None


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
        return [(f"Игрок {uid}: {release.catalog[cid].name}", {"player_id": uid, "card_id": cid})
                for uid in state.order for cid in state.players[uid].in_play
                if (is_item_card(release.catalog[cid]) if rule == "open_item" else release.catalog[cid].kind in {"role", "race"})]
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
        eligible = [cid for cid in player.hand + player.in_play if is_item_card(release.catalog[cid])]
        selected = _selected(data, "selected", eligible)
        total = sum(release.catalog[cid].value for cid in selected)
        lines = ["<b>Продажа вещей</b>", f"Печатная стоимость выбранных вещей: {total} золотых", "Сдачи нет. Подтвердите выбранные вещи."]
        rows = _toggle_rows(eligible, selected, data, "selected", flow, viewer, release)
        args = {"card_ids": selected}
        preview = _action_result(state, viewer, "sell", args, release, now)
        if preview is not None:
            lines.append(f"Получите уровней: {preview.players[viewer].level - player.level}")
            rows.append([Button("Продать выбранные", "sell", args, viewer)])
    elif flow == "charity":
        excess = max(0, len(player.hand) - effective_hand_limit(state, viewer, release.catalog))
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
        offered = [cid for cid in player.in_play if is_item_card(release.catalog[cid])]
        requested = [cid for cid in state.players[partner].in_play if is_item_card(release.catalog[cid])]
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
            eligible = [cid for cid in player.in_play if is_item_card(release.catalog[cid])]
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
        targets = _targets(state, viewer, card.target_rule, release)
        if card.rule_key == "cheat":
            targets += [(release.catalog[item].name, {"player_id": viewer, "card_id": item})
                        for item in player.hand if is_item_card(release.catalog[item])]
        for label, target in targets:
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
        owned = next(((cid, ability) for cid, ability in _ability_sources(player, release) if ability["key"] == key), None)
        if owned is None:
            raise ValueError("ability not owned")
        source, descriptor = owned
        cost = descriptor["cost"]
        eligible = _ability_costs(state, viewer, source, descriptor, release)
        selected = _selected(data, "cost_ids", eligible)
        if cost.get("mode") == "all_hand":
            selected = player.hand.copy()
        automatic = key in {"hireling_escape", "rat_on_a_stick_escape"}
        if automatic:
            selected = [source]
        lines = ["<b>Способность</b>", _ability_label(source, descriptor, release), _ability_cost_text(descriptor), f"Выбрано: {len(selected)} карт"]
        if key == "cleric_resurrection" and state.door_discard:
            lines.append("Верхняя дверь в сбросе: " + card_name(release, state.door_discard[-1]))
        if cost.get("mode") != "all_hand" and not automatic:
            rows = _toggle_rows(eligible, selected, {**data, "ability_key": key}, "cost_ids", flow, viewer, release)
        if len(selected) == cost["count"] or cost.get("mode") == "all_hand":
            for label, target in _ability_targets(state, viewer, key, release):
                args = {"ability_key": key, "cost_ids": selected, "target": target}
                if legal_action(state, viewer, "use_ability", args, release, now):
                    rows.append([Button("Применить: " + label, "use_ability", args, viewer)])
    elif flow == "hireling":
        hireling = data.get("hireling_id")
        if hireling not in player.in_play or release.catalog[hireling].rule_key != "hireling":
            raise ValueError("hireling is not owned")
        lines = ["<b>Вещь наёмника</b>", card_name(release, hireling)]
        for cid in player.hand + player.in_play:
            args = {"hireling_id": hireling, "card_id": cid}
            if legal_action(state, viewer, "assign_hireling", args, release, now):
                rows.append([Button(card_name(release, cid), "assign_hireling", args, viewer)])
    elif flow in {"identity_excess", "big_excess"}:
        identity = flow == "identity_excess"
        if (identity and not player.pending_identity_excess) or (not identity and not player.pending_big_excess):
            raise ValueError("no mandatory excess")
        eligible = player.role_ids + player.race_ids if identity else [cid for cid in player.in_play
                    if is_item_card(release.catalog[cid]) and release.catalog[cid].size == "big" and not ignored_item(player, cid)]
        selected = _selected(data, "selected", eligible)
        lines = ["<b>Обязательный выбор</b>"]
        if identity:
            lines += [f"Лишних классов: {player.pending_identity_excess.get('role', 0)}",
                      f"Лишних происхождений: {player.pending_identity_excess.get('race', 0)}"]
        else:
            lines.append(f"Лишних крупных вещей: {player.pending_big_excess}")
        rows = _toggle_rows(eligible, selected, data, "selected", flow, viewer, release)
        action = "resolve_identity_excess" if identity else "resolve_big_items"
        args = {"card_ids": selected}
        if legal_action(state, viewer, action, args, release, now):
            rows.append([Button("Сбросить выбранные", action, args, viewer)])
        if not identity:
            for uid in state.order:
                transfer = {**args, "recipient_id": uid}
                if legal_action(state, viewer, action, transfer, release, now):
                    rows.append([Button(f"Передать: Игрок {uid}", action, transfer, viewer)])
            if state.active_user_id == viewer and state.combat is None:
                rows.append([_nav("Продать вещи", "sell", viewer)])
    else:
        raise ValueError("unknown selection")
    return View(f"user:{viewer}", "\n".join(lines), rows + [[_nav("Отмена", "main", viewer)]])


def _context_rows(state, viewer, release, now):
    rows = []
    combat = state.combat
    player = state.players[viewer]
    if any(p.pending_identity_excess or p.pending_big_excess for p in state.players.values()):
        if player.pending_identity_excess:
            rows.append([_selection("Выбрать лишние классы / происхождения", "identity_excess", {}, viewer)])
        if player.pending_big_excess:
            rows.append([_selection("Выбрать лишние крупные вещи", "big_excess", {}, viewer)])
            if state.active_user_id == viewer and state.combat is None and not player.pending_identity_excess:
                rows.append([_nav("Продать вещи", "sell", viewer)])
        # Stored escape resolution is still permitted by the core during excess.
        if combat:
            for uid, cid in sorted(combat.escape_rolls):
                if uid == viewer:
                    rows.append([Button("Разрешить побег от " + release.catalog[cid].name, "resolve_escape", {"monster_id": cid}, viewer)])
        return rows
    if state.phase == "lobby":
        rows.append([Button(label, "set_character_sex", {"character_sex": sex}, viewer)
                     for label, sex in (("Мужской", "male"), ("Женский", "female"), ("Случайный", None))])
    if state.phase == "turn.charity" and state.active_user_id == viewer and len(player.hand) > effective_hand_limit(state, viewer, release.catalog):
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
                stored = (uid, cid) in combat.escape_rolls
                rows.append([Button(("Разрешить побег от " if stored else "Бросить кубик: ") + release.catalog[cid].name,
                                    "resolve_escape" if stored else "run_away", {"monster_id": cid}, viewer)])
    if state.corpse:
        rows.append([_nav("Добыча погибших", "corpses", viewer)])
    for cid in player.in_play:
        if cid in player.role_ids + player.race_ids or release.catalog[cid].rule_key in {"half_breed", "super_munchkin"}:
            rows.append([Button("Сбросить " + card_name(release, cid), "discard_identity", {"card_id": cid}, viewer)])
    for cid, ability in _ability_sources(player, release):
        if _ability_available(state, viewer, cid, ability, release, now):
            rows.append([_selection(_ability_label(cid, ability, release), "ability", {"ability_key": ability["key"]}, viewer)])
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
    if screen == "equipment":
        view.rows = [[b for b in row if b.args.get("flow") != "hireling"
                      or any(option.action == "assign_hireling" for options in render_selection(
                          state, viewer_id, "hireling", b.args, release, now=now).rows for option in options)] for row in view.rows]
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
        player = state.players[viewer_id]
        if player.pending_identity_excess or player.pending_big_excess:
            view.text += "\n<b>Сначала разрешите обязательный выбор лишних карт.</b>"
        if combat:
            for (uid, cid), die in sorted(combat.escape_rolls.items()):
                if uid == viewer_id:
                    view.text += f"\n{card_name(release, cid)} · Бросок: {die}. Выберите способность или разрешите побег."
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
                public = [b for b in row if b.action in {"run_away", "resolve_escape", "pass_reaction"}]
                if public:
                    view.rows.append(public)
    if screen != "group" or state.phase != "lobby":
        view.rows = [[b for b in row if b.action in {"nav", "select", "choose_card_target", "trade_partner", "loot_hidden_corpse"}
                      or legal_action(state, b.actor_id, b.action, b.args, release, now)] for row in view.rows]
        view.rows = [row for row in view.rows if row]
    return view
