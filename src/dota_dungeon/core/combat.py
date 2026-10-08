"""Combat totals, help, intervention, rewards, escape and death."""

from copy import deepcopy
from datetime import datetime, timedelta
from random import Random

from .effects import apply_effects
from .model import Catalog, CombatDecision, Event, GameState, RuleError
from .character import identities, matches_identity, start_character_combat
from .items import can_use, is_item_card


def _require_combat(state: GameState) -> None:
    if state.combat is None or state.phase != "combat.active":
        raise RuleError("no active combat")


def combat_strength(state: GameState, user_id: int, catalog: Catalog) -> int:
    player = state.players[user_id]
    cards = (
        set(cid for cid in player.equipped if can_use(player, cid, catalog))
        | set(player.role_ids)
        | set(player.race_ids)
        | set(player.hireling_items.values())
    )
    cards |= {
        cid
        for cid in player.in_play
        if catalog[cid].rule_key in {"hireling", "really_impressive_title"}
    }
    if any(catalog[cid].rule_key == "curse_malign_mirror" for cid in player.in_play):
        cards = {
            cid
            for cid in cards
            if not is_item_card(catalog[cid]) or catalog[cid].slots == "armor"
        }
    bonus = sum(catalog[cid].bonus for cid in cards)
    for cid in cards:
        for condition in catalog[cid].conditions:
            if condition["rule_key"] == "item_identity_bonus" and matches_identity(
                player, catalog, condition["args"]
            ):
                bonus += condition["args"]["amount"]
    return (
        player.level
        + player.strength_bonus
        + bonus
        + (
            state.combat.temporary_strength.get(user_id, 0)
            + state.combat.character_penalties.get(user_id, 0)
            if state.combat
            else 0
        )
    )


def combat_totals(state: GameState, catalog: Catalog) -> tuple[int, int]:
    if not state.combat:
        raise RuleError("no combat")
    fighters = sum(
        combat_strength(state, uid, catalog) for uid in state.combat.fighter_ids
    )
    keys = {
        d["rule_key"]
        for mid in state.combat.monster_ids
        for d in monster_card(state, mid, catalog).conditions
    }
    if "level_only_combat" in keys:
        fighters = sum(state.players[u].level for u in state.combat.fighter_ids)
    elif "bonuses_only_combat" in keys:
        fighters -= sum(state.players[u].level for u in state.combat.fighter_ids)
    if state.combat.double_strength:
        fighters *= 2
    monsters = sum(
        monster_strength(state, cid, catalog) for cid in state.combat.monster_ids
    )
    monsters += state.combat.monster_strength_bonus
    monsters += sum(
        catalog[cid].bonus
        for cid in state.combat.modifier_ids
        if not any(
            m.get("card_id") == cid
            for mods in state.combat.monster_modifiers.values()
            for m in mods
        )
    )
    return fighters, monsters


def declare_result(state: GameState, actor_id: int, catalog: Catalog) -> CombatDecision:
    _require_combat(state)
    if actor_id != leader_id(state):
        raise RuleError("only active fighter can declare result")
    if any(
        (
            state.players[uid].pending_big_excess
            or state.players[uid].pending_identity_excess
        )
        for uid in state.combat.fighter_ids
    ):
        raise RuleError("resolve excess Big Items first")
    fighters, monsters = combat_totals(state, catalog)
    wins_ties = any(
        "warrior" in identities(state.players[uid], catalog, "role")
        for uid in state.combat.fighter_ids
    )
    return CombatDecision(
        "provisional_win"
        if fighters > monsters or (fighters == monsters and wins_ties)
        else "must_run_away"
    )


def ask_help(
    state: GameState,
    actor_id: int,
    helper_id: int,
    treasure_count: int,
    item_ids: list[str],
    catalog: Catalog,
) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if actor_id != leader_id(state):
        raise RuleError("only active fighter can ask for help")
    if any(
        any(
            d["rule_key"] == "no_helper"
            for d in monster_card(state, m, catalog).conditions
        )
        for m in state.combat.monster_ids
    ):
        raise RuleError("monster forbids help")
    if state.combat.double_strength:
        raise RuleError("Doppleganger requires solo fighter")
    if (
        helper_id not in state.players
        or not state.players[helper_id].alive
        or helper_id == actor_id
    ):
        raise RuleError("invalid helper")
    if state.combat.helper_id is not None or state.combat.pending_help is not None:
        raise RuleError("combat already has a helper offer")
    if treasure_count < 0:
        raise RuleError("negative treasure offer")
    available = sum(
        monster_rewards(state, cid, catalog)[1] for cid in state.combat.monster_ids
    )
    if treasure_count > available:
        raise RuleError("promised treasure exceeds monster reward")
    if len(item_ids) != len(set(item_ids)) or any(
        cid not in state.players[actor_id].in_play for cid in item_ids
    ):
        raise RuleError("promised item must be in play")
    if any(not is_item_card(catalog[cid]) for cid in item_ids):
        raise RuleError("only items can be promised")
    result = deepcopy(state)
    result.combat.pending_help = (helper_id, treasure_count, item_ids.copy())
    return result, [
        Event(
            f"user:{helper_id}",
            "help.offered",
            {
                "fighter_id": actor_id,
                "treasure_count": treasure_count,
                "item_ids": item_ids.copy(),
            },
        )
    ]


def accept_help(
    state: GameState,
    actor_id: int,
    catalog: Catalog | None = None,
    *,
    now=None,
    rng=None,
) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if state.combat.pending_help is None or state.combat.pending_help[0] != actor_id:
        raise RuleError("no help offer for this player")
    result = deepcopy(state)
    _, treasures, items = result.combat.pending_help
    result.combat.pending_help = None
    result.combat.helper_id = actor_id
    result.combat.forced_helper = False
    result.combat.help_treasure_count = treasures
    result.combat.help_item_ids = items
    result.combat.fighter_ids.append(actor_id)
    if catalog is not None:
        from .character import start_character_combat

        start_character_combat(result, catalog)
    result.combat.reaction_deadline = None
    result.combat.passes.clear()
    from .trade import cancel_trades_for_combat

    events = [Event("group", "help.accepted", {"helper_id": actor_id})]
    events.extend(cancel_trades_for_combat(result, actor_id))
    if catalog is not None:
        result, ev = settle_mandatory_monsters(result, catalog, rng or Random(), now)
        events.extend(ev)
    return result, events


def restart_reaction(
    state: GameState, catalog: Catalog, now: datetime, was_reacting: bool
) -> list[Event]:
    """Invalidate passes after intervention and restart a still-winning window."""
    combat = state.combat
    for cid in combat.modifier_ids:
        if cid not in combat.played_card_ids:
            combat.played_card_ids.append(cid)
    combat.passes.clear()
    combat.reaction_deadline = None
    if (
        was_reacting
        and state.phase == "combat.active"
        and declare_result(state, leader_id(state), catalog).outcome
        == "provisional_win"
    ):
        combat.reaction_deadline = now + timedelta(seconds=combat.reaction_seconds)
        return [
            Event(
                "group",
                "combat.reaction_restarted",
                {"deadline": combat.reaction_deadline.isoformat()},
            )
        ]
    return []


def play_combat_card(
    state: GameState,
    actor_id: int,
    card_id: str,
    target_id: str,
    catalog: Catalog,
    now: datetime,
) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if card_id not in catalog:
        raise RuleError("unknown combat card")
    from dataclasses import replace
    from .play import play_card

    card = catalog[card_id]
    if card.kind not in {"modifier", "one_shot", "curse"}:
        raise RuleError("card cannot be played in combat")
    if card.kind == "modifier":
        target = {"monster_id": target_id}
        rule = "monster"
    else:
        try:
            player_id = int(target_id)
        except (ValueError, TypeError) as exc:
            raise RuleError("invalid player target") from exc
        target = {"player_id": player_id}
        rule = "player"
    # Compatibility for old test catalogs; releases retain their declared policy.
    adapted = catalog
    if not card.play_phases and card.rule_key is None:
        adapted = dict(catalog)
        adapted[card_id] = replace(
            card, play_phases=("combat.active",), target_rule=rule
        )
    result, events = play_card(state, actor_id, card_id, target, adapted, Random(), now)
    events = [event for event in events if event.name != "card.played"]
    events.insert(
        0,
        Event(
            "group",
            "combat.card_played",
            {"actor_id": actor_id, "card_id": card_id, "target_id": target_id},
        ),
    )
    return result, events


def decline_help(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if (
        actor_id not in state.players
        or state.combat.pending_help is None
        or state.combat.pending_help[0] != actor_id
    ):
        raise RuleError("no help offer for this player")
    result = deepcopy(state)
    result.combat.pending_help = None
    return result, [
        Event(f"user:{state.active_user_id}", "help.declined", {"helper_id": actor_id})
    ]


def declare_win(
    state: GameState, actor_id: int, catalog: Catalog, now: datetime, seconds: int = 30
) -> tuple[GameState, list[Event]]:
    if declare_result(state, actor_id, catalog).outcome != "provisional_win":
        raise RuleError("fighters are not winning")
    result = deepcopy(state)
    result.combat.passes.clear()
    result.combat.reaction_seconds = seconds
    result.combat.reaction_deadline = now + timedelta(seconds=seconds)
    return result, [
        Event(
            "group",
            "combat.win_declared",
            {"deadline": result.combat.reaction_deadline.isoformat()},
        )
    ]


def pass_reaction(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if state.combat.reaction_deadline is None:
        raise RuleError("no reaction window")
    if actor_id not in state.order or actor_id in state.combat.fighter_ids:
        raise RuleError("fighter cannot pass reaction")
    result = deepcopy(state)
    result.combat.passes.add(actor_id)
    return result, [Event("group", "combat.passed", {"user_id": actor_id})]


def resolve_rewards(state, catalog, rng=None, *, resurrection_ids=None, now=None):
    _require_combat(state)
    transition_rng = deepcopy(rng) if rng is not None else Random()
    result, events = settle_combat(
        deepcopy(state),
        catalog,
        transition_rng,
        success=True,
        now=now,
        resurrection_ids=resurrection_ids,
    )
    if rng is not None and hasattr(rng, "setstate"):
        rng.setstate(transition_rng.getstate())
    return result, events


def close_reaction(
    state: GameState,
    catalog: Catalog,
    now: datetime,
    rng: Random | None = None,
    *,
    resurrection_ids: dict[int, list[str]] | None = None,
) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    combat = state.combat
    if combat.reaction_deadline is None:
        raise RuleError("no reaction window")
    eligible = set(state.order) - set(combat.fighter_ids)
    if now < combat.reaction_deadline and not eligible.issubset(combat.passes):
        raise RuleError("reaction window is still open")
    if declare_result(state, leader_id(state), catalog).outcome != "provisional_win":
        raise RuleError("fighters are no longer winning")
    return resolve_rewards(
        state, catalog, rng, resurrection_ids=resurrection_ids, now=now
    )


def begin_escape(
    state: GameState, actor_id: int, catalog: Catalog
) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if actor_id != leader_id(state):
        raise RuleError("only active fighter can begin escape")
    if declare_result(state, actor_id, catalog).outcome != "must_run_away":
        raise RuleError("fighters can still win")
    result = deepcopy(state)
    result.phase = "combat.run_away"
    result.combat.escape_pending = {
        (user_id, monster_id)
        for user_id in result.combat.fighter_ids
        for monster_id in result.combat.monster_ids
    }
    for uid in result.combat.fighter_ids:
        from .monster_rules import has_condition, condition

        pursued = []
        for mid in result.combat.monster_ids:
            args = has_condition(monster_card(result, mid, catalog), "will_not_pursue")
            if args is not None and condition("will_not_pursue")(
                result, uid, uid, catalog, args
            ):
                result.combat.escape_no_pursuit.add((uid, mid))
            else:
                pursued.append(mid)
        amount = sum(
            d["args"]["amount"]
            for mid in pursued
            for d in monster_card(result, mid, catalog).conditions
            if d["rule_key"] == "run_away_loses_levels"
        )
        result.players[uid].level = max(1, result.players[uid].level - amount)
    return result, [Event("group", "combat.escape_started", {})]


def escape_modifier(
    state: GameState, actor_id: int, monster_id: str, catalog: Catalog
) -> int:
    p = state.players[actor_id]
    bonus = sum(
        x["args"]["amount"]
        for x in monster_card(state, monster_id, catalog).conditions
        if x["rule_key"] == "escape_bonus"
    )
    bonus -= sum(catalog[c].rule_key == "curse_chicken_on_your_head" for c in p.in_play)
    bonus += p.escape_bonus + (1 if "elf" in identities(p, catalog, "race") else 0)
    for cid in p.equipped:
        if not can_use(p, cid, catalog):
            continue
        for condition in catalog[cid].conditions:
            if condition["rule_key"] in {"item_escape_bonus", "tuba_escape"}:
                bonus += condition["args"]["amount"]
    if state.combat:
        bonus += state.combat.escape_bonuses.get((actor_id, monster_id), 0)
    return bonus


def _discard_combat_cards(state: GameState) -> None:
    for cid in dict.fromkeys(
        state.combat.retired_monster_ids
        + state.combat.monster_ids
        + state.combat.charmed_monster_ids
        + state.combat.played_card_ids
        + state.combat.modifier_ids
    ):
        if cid in state.combat.virtual_monsters:
            continue
        (
            state.door_discard
            if state.card_decks.get(cid, "door") == "door"
            else state.treasure_discard
        ).append(cid)


def apply_bad_stuff(state, actor_id, monster_id, catalog, *, rng=None, now=None):
    if state.combat is None or monster_id not in state.combat.monster_ids:
        raise RuleError("unknown combat monster")
    if (actor_id, monster_id) in state.combat.prevented_bad_stuff or not state.players[
        actor_id
    ].alive:
        return deepcopy(state), [
            Event("group", "bad_stuff.prevented", {"user_id": actor_id})
        ]
    result = deepcopy(state)
    transition_rng = deepcopy(rng) if rng is not None else Random()
    effects = [
        {"op": "special", "rule_key": "death", "args": {}} if e["op"] == "death" else e
        for e in monster_card(state, monster_id, catalog).bad_stuff
    ]
    result, events = apply_effects(
        result,
        actor_id,
        effects,
        catalog,
        choices={"actor_id": actor_id, "_now": now},
        rng=transition_rng,
    )
    if rng is not None and hasattr(rng, "setstate"):
        rng.setstate(transition_rng.getstate())
    return result, events


def finish_escape_attempt(
    state: GameState,
    actor_id: int,
    monster_id: str,
    escaped: bool,
    catalog: Catalog,
    rng: Random | None = None,
    now: datetime | None = None,
):
    if (
        state.phase != "combat.run_away"
        or state.combat is None
        or (actor_id, monster_id) not in state.combat.escape_pending
    ):
        raise RuleError("no escape attempt")
    result = deepcopy(state)
    pair = (actor_id, monster_id)
    events = []
    result.combat.escape_pending.remove(pair)
    result.combat.escape_rolls.pop(pair, None)
    result.combat.escape_outcomes[pair] = escaped
    if not escaped:
        result, bad_events = apply_bad_stuff(
            result, actor_id, monster_id, catalog, rng=rng, now=now
        )
        events.extend(bad_events)
        if not result.players[actor_id].alive:
            result.combat.escape_pending = {
                p for p in result.combat.escape_pending if p[0] != actor_id
            }
            result.combat.escape_rolls = {
                p: die
                for p, die in result.combat.escape_rolls.items()
                if p[0] != actor_id
            }
    result.combat.automatic_escapes.discard(pair)
    result.combat.escape_roll_ids.pop(pair, None)
    if not result.combat.escape_rolls:
        result.combat.escape_deadline = None
    if result.pending_decision:
        result.resolution_queue.append(dict(kind="escape_finish", actor=actor_id))
        return result, events
    result, ev = complete_escape(result, actor_id, catalog, rng, now)
    return result, events + ev


def complete_escape(result, actor_id, catalog, rng=None, now=None):
    events = []
    if (
        not any(p[0] == actor_id for p in result.combat.escape_pending)
        and actor_id not in result.combat.tuba_rewarded
        and all(
            success
            for p, success in result.combat.escape_outcomes.items()
            if p[0] == actor_id
        )
    ):
        p = result.players[actor_id]
        if any(
            catalog[cid].rule_key == "tuba_of_charm" and can_use(p, cid, catalog)
            for cid in p.equipped
        ):
            result.combat.tuba_rewarded.add(actor_id)
            from .draw import draw_cards

            transition_rng = deepcopy(rng) if rng is not None else Random()
            result, drawn = draw_cards(
                result, actor_id, "treasure", 1, False, catalog, transition_rng
            )
            events.extend(drawn)
            if rng is not None and hasattr(rng, "setstate"):
                rng.setstate(transition_rng.getstate())
    if not result.combat.escape_pending:
        result, ev = settle_combat(
            result, catalog, rng or Random(), success=False, now=now
        )
        events.extend(ev)
        events.append(Event("group", "combat.escape_finished", {}))
    return result, events


def resolve_escape(
    state: GameState,
    actor_id: int,
    monster_id: str,
    catalog: Catalog,
    rng: Random | None = None,
    now: datetime | None = None,
):
    validate_escape_action(
        state, actor_id, "resolve_escape", {"monster_id": monster_id}, catalog
    )
    pair = (actor_id, monster_id)
    if not state.combat or pair not in state.combat.escape_rolls:
        raise RuleError("no stored escape roll")
    escaped = pair in state.combat.automatic_escapes or (
        state.combat.escape_rolls[pair]
        + escape_modifier(state, actor_id, monster_id, catalog)
        >= 5
    )
    result, events = finish_escape_attempt(
        state, actor_id, monster_id, escaped, catalog, rng, now
    )
    events.insert(
        0,
        Event(
            "group",
            "escape.resolved",
            {"user_id": actor_id, "monster_id": monster_id, "escaped": escaped},
        ),
    )
    return result, events


def run_away(
    state: GameState,
    actor_id: int,
    monster_id: str,
    rng: Random,
    catalog: Catalog,
    *,
    now: datetime | None = None,
) -> tuple[GameState, list[Event]]:
    validate_escape_action(state, actor_id, "run_away", {}, catalog)
    if state.phase != "combat.run_away" or state.combat is None:
        raise RuleError("no escape in progress")
    pair = (actor_id, monster_id)
    if pair not in state.combat.escape_pending or pair in state.combat.escape_rolls:
        raise RuleError("escape roll already resolved or invalid")
    result = deepcopy(state)
    transition_rng = deepcopy(rng)
    from .monster_rules import has_condition, condition

    card = monster_card(result, monster_id, catalog)
    if has_condition(card, "cannot_run_away") is not None:
        result, events = finish_escape_attempt(
            result, actor_id, monster_id, False, catalog, transition_rng, now
        )
    elif pair in result.combat.escape_no_pursuit:
        result, events = finish_escape_attempt(
            result, actor_id, monster_id, True, catalog, transition_rng, now
        )
    elif has_condition(card, "automatic_escape") is not None:
        result, events = offer_automatic_escape(
            result, actor_id, monster_id, catalog, transition_rng, now
        )
    else:
        result = None
    if result is not None:
        if hasattr(rng, "setstate"):
            rng.setstate(transition_rng.getstate())
        return result, events
    result = deepcopy(state)
    die = transition_rng.randint(1, 6)
    result.combat.escape_rolls[pair] = die
    stamp_escape(result, pair, now)
    escaped = die + escape_modifier(result, actor_id, monster_id, catalog) >= 5
    events = [
        Event(
            "group",
            "escape.rolled",
            {
                "user_id": actor_id,
                "monster_id": monster_id,
                "die": die,
                "escaped": escaped,
            },
        )
    ]
    # Opportunity timing is public catalog policy, independent of hidden hands.
    after_roll = any(
        card.rule_key
        in {"loaded_die", "invisibility_potion", "magic_lamp", "flask_of_glue"}
        or any(
            a["key"] in {"wizard_flight", "halfling_escape_retry"}
            for a in card.abilities
        )
        for card in catalog.values()
    )
    if after_roll:
        events.append(
            Event(
                f"user:{actor_id}",
                "escape.decision_required",
                {
                    "user_id": actor_id,
                    "monster_id": monster_id,
                    "die": die,
                    "escaped": escaped,
                },
            )
        )
    else:
        result, resolved = resolve_escape(
            result, actor_id, monster_id, catalog, transition_rng, now
        )
        events.extend(resolved)
    if hasattr(rng, "setstate"):
        rng.setstate(transition_rng.getstate())
    return result, events


def loot_corpse(
    state: GameState, actor_id: int, deceased_id: int, card_id: str
) -> tuple[GameState, list[Event]]:
    if (
        actor_id == deceased_id
        or actor_id not in state.players
        or not state.players[actor_id].alive
    ):
        raise RuleError("invalid corpse looter")
    if deceased_id not in state.corpse or card_id not in state.corpse[deceased_id]:
        raise RuleError("card is not on corpse")
    if actor_id in state.corpse_looted_by.get(deceased_id, set()):
        raise RuleError("player already looted corpse")
    order = state.corpse_loot_order.get(deceased_id, [])
    if order and actor_id != order[0]:
        raise RuleError("higher-level corpse looter acts first")
    result = deepcopy(state)
    if order:
        result.corpse_loot_order[deceased_id].pop(0)
    result.corpse[deceased_id].remove(card_id)
    result.corpse_looted_by[deceased_id].add(actor_id)
    if card_id in result.corpse_hand.get(deceased_id, set()):
        result.players[actor_id].hand.append(card_id)
        result.corpse_hand[deceased_id].remove(card_id)
    else:
        result.players[actor_id].in_play.append(card_id)
    if order and not result.corpse_loot_order[deceased_id]:
        for cid in result.corpse[deceased_id]:
            getattr(result, f'{result.card_decks.get(cid,"treasure")}_discard').append(
                cid
            )
        result.corpse[deceased_id] = []
        result.corpse_hand[deceased_id] = set()
    return result, [
        Event(
            "group",
            "corpse.looted",
            {"user_id": actor_id, "deceased_id": deceased_id, "card_id": card_id},
        )
    ]


def validate_escape_action(state, actor_id, action, target, catalog, *, rule_key=None):
    """Only printed after-roll exceptions may precede a stored die's consequences.

    Task 6 registers the future card handlers; admission here never supplies one.
    Ownership and card-specific operands remain validated by their normal handler.
    """
    if action in {"respond_decision", "expire_decision", "expire_escape"}:
        return
    if not state.combat or not state.combat.escape_rolls:
        return
    if not isinstance(target, dict):
        raise RuleError("invalid stored-roll target")
    rolls = state.combat.escape_rolls
    if action in {"resolve_escape", "use_ability"}:
        pair = (actor_id, target.get("monster_id"))
        if pair in rolls and (
            action == "resolve_escape"
            or rule_key in {"wizard_flight", "halfling_escape_retry"}
        ):
            return
    elif action == "play_card":
        if rule_key == "flask_of_glue":
            matching = [pair for pair in rolls if pair[0] == target.get("player_id")]
        else:
            matching = [pair for pair in rolls if pair[0] == actor_id]
        for pair in matching:
            escaped = pair in state.combat.automatic_escapes or (
                rolls[pair] + escape_modifier(state, pair[0], pair[1], catalog) >= 5
            )
            if rule_key == "loaded_die":
                return
            if rule_key == "invisibility_potion" and not escaped:
                return
            if (
                rule_key == "magic_lamp"
                and actor_id == state.active_user_id
                and target.get("monster_id") == pair[1]
                and not escaped
            ):
                return
            if rule_key == "flask_of_glue" and escaped:
                return
    raise RuleError("resolve stored escape roll before unrelated actions")


def leader_id(state):
    return (
        (state.combat.leader_id or state.combat.fighter_ids[0])
        if state.combat
        else state.active_user_id
    )


def monster_card(state, monster_id, catalog):
    return catalog[state.combat.virtual_monsters.get(monster_id, monster_id)]


def monster_rewards(state, monster_id, catalog):
    card = monster_card(state, monster_id, catalog)
    mods = state.combat.monster_modifiers.get(monster_id, [])
    treasures = card.treasures + sum(m.get("treasures", 0) for m in mods)
    minimum = max((m.get("minimum_treasures", 0) for m in mods), default=0)
    from .monster_rules import condition

    levels = card.levels
    for d in card.conditions:
        if d["rule_key"] in {
            "extra_level_if_fire_flame",
            "extra_level_if_solo_without_bonuses",
            "elf_extra_treasure",
        } and condition(d["rule_key"])(
            state, leader_id(state), leader_id(state), catalog, d["args"]
        ):
            if d["rule_key"] == "elf_extra_treasure":
                treasures += d["args"]["amount"]
            else:
                levels += d["args"]["amount"]
    return levels, max(minimum, treasures)


def monster_strength(state, monster_id, catalog):
    card = monster_card(state, monster_id, catalog)
    mods = state.combat.monster_modifiers.get(monster_id, [])
    strength = card.bonus + sum(m.get("amount", 0) for m in mods)
    for condition in card.conditions:
        if condition["rule_key"] == "monster_bonus" and any(
            matches_identity(
                state.players[uid], catalog, condition["args"], disadvantage=True
            )
            for uid in state.combat.fighter_ids
        ):
            strength += condition["args"]["amount"]
    return max(
        max((m.get("minimum_monster_level", 0) for m in mods), default=0), strength
    )


def add_enhancer(state, monster_id, amount, treasures=0, *, card_id=None, **limits):
    combat = state.combat
    if not combat or monster_id not in combat.monster_ids:
        raise RuleError("unknown combat monster")
    group = combat.enhancer_groups.setdefault(monster_id, monster_id)
    for mid in combat.monster_ids:
        if combat.enhancer_groups.get(mid, mid) == group:
            combat.monster_modifiers.setdefault(mid, []).append(
                dict(amount=amount, treasures=treasures, card_id=card_id, **limits)
            )


def reconcile_monsters(state, catalog):
    c = state.combat
    if any(
        any(
            x["rule_key"] == "no_helper"
            for x in monster_card(state, m, catalog).conditions
        )
        for m in c.monster_ids
    ):
        c.fighter_ids = [leader_id(state)]
        c.helper_id = None
        c.forced_helper = False
        c.pending_help = None
        c.help_item_ids = []
        c.help_treasure_count = 0


def join_undead(state, actor_id, card_id, catalog, now):
    _require_combat(state)
    if (
        card_id not in state.players[actor_id].hand
        or "undead" not in catalog[card_id].tags
    ):
        raise RuleError("an owned Undead monster is required")
    if not any(
        "undead" in monster_card(state, m, catalog).tags
        for m in state.combat.monster_ids
    ):
        raise RuleError("no Undead monster in combat")
    result = deepcopy(state)
    result.players[actor_id].hand.remove(card_id)
    result.combat.monster_ids.append(card_id)
    reconcile_monsters(result, catalog)
    events = restart_reaction(
        result, catalog, now, bool(state.combat.reaction_deadline)
    )
    return result, events + [
        Event("group", "combat.monster_added", {"monster_id": card_id})
    ]


def remove_foe(
    state,
    monster_id,
    catalog,
    rng,
    *,
    outcome="removal",
    levels=0,
    treasures=0,
    now=None,
):
    c = state.combat
    if not c or monster_id not in c.monster_ids:
        raise RuleError("unknown combat monster")
    c.pending_rewards.append(
        dict(
            monster_id=monster_id,
            beneficiary=leader_id(state),
            levels=levels,
            treasures=treasures,
            kill=outcome == "kill",
            outcome=outcome,
            helper_id=c.helper_id,
            helper_treasure_count=c.help_treasure_count,
            helper_item_ids=c.help_item_ids.copy(),
            helper_elf=bool(
                c.helper_id
                and "elf" in identities(state.players[c.helper_id], catalog, "race")
            ),
        )
    )
    c.monster_ids.remove(monster_id)
    if monster_id not in c.virtual_monsters:
        c.retired_monster_ids.append(monster_id)
    c.escape_pending = {pair for pair in c.escape_pending if pair[1] != monster_id}
    c.escape_rolls = {
        pair: die for pair, die in c.escape_rolls.items() if pair[1] != monster_id
    }
    if not c.monster_ids:
        return settle_combat(state, catalog, rng, success=True, now=now)
    return state, [
        Event(
            "group",
            "combat.monster_removed",
            {"monster_id": monster_id, "outcome": outcome},
        )
    ]


def settle_combat(state, catalog, rng, *, success, now=None, resurrection_ids=None):
    from .reward_rules import begin_rewards

    return begin_rewards(state, catalog, rng, now, success, selections=resurrection_ids)


from .monster_rules import monster_action_options, monster_action, force_help


def stamp_escape(state, pair, now):
    from .decisions import time_value

    state.decision_seq += 1
    state.combat.escape_roll_ids[pair] = f"escape:{state.decision_seq}"
    state.combat.escape_deadline = time_value(now) + timedelta(seconds=30)


def escape_possible(state, monster_id, catalog):
    return not any(
        d["rule_key"] == "cannot_run_away"
        for d in monster_card(state, monster_id, catalog).conditions
    )


def offer_automatic_escape(state, actor, monster_id, catalog, rng, now=None):
    if not escape_possible(state, monster_id, catalog):
        raise RuleError("monster forbids escape")
    if any(c.rule_key == "flask_of_glue" for c in catalog.values()):
        pair = (actor, monster_id)
        state.combat.escape_rolls[pair] = 6
        state.combat.automatic_escapes.add(pair)
        stamp_escape(state, pair, now)
        return state, [
            Event(
                "group",
                "escape.automatic_pending",
                {
                    "user_id": actor,
                    "monster_id": monster_id,
                    "roll_id": state.combat.escape_roll_ids[pair],
                    "deadline": state.combat.escape_deadline.isoformat(),
                },
            )
        ]
    return finish_escape_attempt(state, actor, monster_id, True, catalog, rng, now)


def expire_escape(state, actor, player_id, monster_id, roll_id, catalog, rng, now):
    c = state.combat
    pair = (player_id, monster_id)
    if (
        not c
        or actor != state.active_user_id
        or c.escape_roll_ids.get(pair) != roll_id
        or c.escape_deadline is None
        or now < c.escape_deadline
    ):
        raise RuleError("escape deadline not reached or stale")
    return resolve_escape(state, player_id, monster_id, catalog, rng, now)


def settle_mandatory_monsters(state, catalog, rng, now):
    from .monster_rules import has_condition

    events = []
    if not state.combat:
        return state, events
    reconcile_monsters(state, catalog)
    c = state.combat
    if c.forced_helper and c.helper_id is not None:
        leader = leader_id(state)
        pending = sum(
            e["levels"] for e in c.pending_rewards if e["beneficiary"] == leader
        )
        attainable = (
            state.players[leader].level
            + pending
            + sum(monster_rewards(state, mid, catalog)[0] for mid in c.monster_ids)
        )
        if attainable >= 10:
            helper = c.helper_id
            c.fighter_ids = [leader]
            c.helper_id = None
            c.forced_helper = False
            c.help_treasure_count = 0
            c.help_item_ids = []
            events.append(
                Event(
                    "group",
                    "help.forced_left",
                    {"helper_id": helper, "reason": "winning_level"},
                )
            )
    for mid in list(state.combat.monster_ids):
        card = monster_card(state, mid, catalog)
        if has_condition(card, "amazon_female") is not None and any(
            state.players[u].character_sex == "female" for u in state.combat.fighter_ids
        ):
            state, ev = remove_foe(
                state, mid, catalog, rng, outcome="avoidance", treasures=1, now=now
            )
            events.extend(ev)
            if not state.combat:
                return state, events
        elif has_condition(card, "no_attack_and_exchange") is not None:
            thieves = [
                uid
                for uid in state.combat.fighter_ids
                if "thief" in identities(state.players[uid], catalog, "role")
            ]
            if thieves:
                uid = thieves[0]
                from .decisions import offer

                cards = [
                    cid
                    for cid in state.players[uid].hand + state.players[uid].in_play
                    if catalog[cid].deck == "treasure"
                ]
                if len(cards) < 2:
                    state, ev = remove_foe(
                        state, mid, catalog, rng, outcome="avoidance", now=now
                    )
                    events.extend(ev)
                    if not state.combat:
                        return state, events
                else:
                    events.extend(
                        offer(
                            state,
                            "loss_choice",
                            [uid],
                            dict(
                                victim=uid,
                                rule="lawyers",
                                monster_id=mid,
                                card_ids=cards,
                                count=None,
                                minimum_value=None,
                                options=[],
                                recipient=None,
                                amount=None,
                            ),
                            now,
                        )
                    )
                    return state, events
        elif has_condition(card, "discard_item_before_combat") is not None:
            for uid in state.combat.fighter_ids:
                pair = (uid, mid)
                if pair not in state.combat.entry_processed:
                    state.combat.entry_processed.add(pair)
                    state.resolution_queue.append(
                        dict(kind="loss", args=dict(victim=uid, count=1))
                    )
    if state.resolution_queue and not state.pending_decision:
        from .decisions import drain

        state, ev = drain(state, catalog, rng, now)
        events.extend(ev)
    return state, events
