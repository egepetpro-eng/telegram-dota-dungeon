"""Combat totals, help, intervention, rewards, escape and death."""

from copy import deepcopy
from datetime import datetime, timedelta
from random import Random

from .effects import apply_effects
from .model import Catalog, CombatDecision, Event, GameState, RuleError


def _require_combat(state: GameState) -> None:
    if state.combat is None or state.phase != "combat.active":
        raise RuleError("no active combat")


def combat_strength(state: GameState, user_id: int, catalog: Catalog) -> int:
    player = state.players[user_id]
    cards = set(player.equipped) | set(player.role_ids) | set(player.race_ids)
    return (player.level + player.strength_bonus + sum(catalog[cid].bonus for cid in cards)
            + (state.combat.temporary_strength.get(user_id, 0) if state.combat else 0))


def declare_result(state: GameState, actor_id: int, catalog: Catalog) -> CombatDecision:
    _require_combat(state)
    if actor_id != state.active_user_id:
        raise RuleError("only active fighter can declare result")
    fighters = sum(combat_strength(state, user_id, catalog) for user_id in state.combat.fighter_ids)
    monsters = (sum(catalog[cid].bonus for cid in state.combat.monster_ids)
                + sum(catalog[cid].bonus for cid in state.combat.modifier_ids)
                + state.combat.monster_strength_bonus)
    return CombatDecision("provisional_win" if fighters > monsters else "must_run_away")


def ask_help(state: GameState, actor_id: int, helper_id: int, treasure_count: int,
             item_ids: list[str], catalog: Catalog) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if actor_id != state.active_user_id:
        raise RuleError("only active fighter can ask for help")
    if helper_id not in state.players or helper_id == actor_id:
        raise RuleError("invalid helper")
    if state.combat.helper_id is not None or state.combat.pending_help is not None:
        raise RuleError("combat already has a helper offer")
    if treasure_count < 0:
        raise RuleError("negative treasure offer")
    available = sum(catalog[cid].treasures for cid in state.combat.monster_ids)
    if treasure_count > available:
        raise RuleError("promised treasure exceeds monster reward")
    if len(item_ids) != len(set(item_ids)) or any(cid not in state.players[actor_id].in_play for cid in item_ids):
        raise RuleError("promised item must be in play")
    if any(catalog[cid].kind != "item" for cid in item_ids):
        raise RuleError("only items can be promised")
    result = deepcopy(state)
    result.combat.pending_help = (helper_id, treasure_count, item_ids.copy())
    return result, [Event(f"user:{helper_id}", "help.offered", {
        "fighter_id": actor_id, "treasure_count": treasure_count, "item_ids": item_ids.copy()})]


def accept_help(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if state.combat.pending_help is None or state.combat.pending_help[0] != actor_id:
        raise RuleError("no help offer for this player")
    result = deepcopy(state)
    _, treasures, items = result.combat.pending_help
    result.combat.pending_help = None
    result.combat.helper_id = actor_id
    result.combat.help_treasure_count = treasures
    result.combat.help_item_ids = items
    result.combat.fighter_ids.append(actor_id)
    result.combat.reaction_deadline = None
    result.combat.passes.clear()
    from .trade import cancel_trades_for_combat
    events = [Event("group", "help.accepted", {"helper_id": actor_id})]
    events.extend(cancel_trades_for_combat(result, actor_id))
    return result, events


def restart_reaction(state: GameState, catalog: Catalog, now: datetime,
                     was_reacting: bool) -> list[Event]:
    """Invalidate passes after intervention and restart a still-winning window."""
    combat = state.combat
    for cid in combat.modifier_ids:
        if cid not in combat.played_card_ids:
            combat.played_card_ids.append(cid)
    combat.passes.clear()
    combat.reaction_deadline = None
    if was_reacting and state.phase == "combat.active" and declare_result(state, state.active_user_id, catalog).outcome == "provisional_win":
        combat.reaction_deadline = now + timedelta(seconds=30)
        return [Event("group", "combat.reaction_restarted", {"deadline": combat.reaction_deadline.isoformat()})]
    return []


def play_combat_card(state: GameState, actor_id: int, card_id: str,
                     target_id: str, catalog: Catalog,
                     now: datetime) -> tuple[GameState, list[Event]]:
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
        adapted[card_id] = replace(card, play_phases=("combat.active",), target_rule=rule)
    result, events = play_card(state, actor_id, card_id, target, adapted, Random(), now)
    events = [event for event in events if event.name != "card.played"]
    events.insert(0, Event("group", "combat.card_played", {
        "actor_id": actor_id, "card_id": card_id, "target_id": target_id}))
    return result, events


def decline_help(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if actor_id not in state.players or state.combat.pending_help is None or state.combat.pending_help[0] != actor_id:
        raise RuleError("no help offer for this player")
    result = deepcopy(state)
    result.combat.pending_help = None
    return result, [Event(f"user:{state.active_user_id}", "help.declined", {"helper_id": actor_id})]


def declare_win(state: GameState, actor_id: int, catalog: Catalog,
                now: datetime, seconds: int = 30) -> tuple[GameState, list[Event]]:
    if declare_result(state, actor_id, catalog).outcome != "provisional_win":
        raise RuleError("fighters are not winning")
    result = deepcopy(state)
    result.combat.passes.clear()
    result.combat.reaction_deadline = now + timedelta(seconds=seconds)
    return result, [Event("group", "combat.win_declared", {"deadline": result.combat.reaction_deadline.isoformat()})]


def pass_reaction(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if state.combat.reaction_deadline is None:
        raise RuleError("no reaction window")
    if actor_id not in state.order or actor_id in state.combat.fighter_ids:
        raise RuleError("fighter cannot pass reaction")
    result = deepcopy(state)
    result.combat.passes.add(actor_id)
    return result, [Event("group", "combat.passed", {"user_id": actor_id})]


def resolve_rewards(state: GameState, catalog: Catalog,
                    rng: Random | None = None) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    result = deepcopy(state)
    combat = result.combat
    leader = result.players[result.active_user_id]
    levels = sum(catalog[cid].levels for cid in combat.monster_ids)
    treasures = sum(catalog[cid].treasures for cid in combat.monster_ids)
    if combat.help_treasure_count > treasures:
        raise RuleError("promised treasure exceeds reward")
    for cid in combat.help_item_ids:
        if cid not in leader.in_play:
            raise RuleError("promised item changed owner")
    leader.level = min(10, leader.level + levels)
    events = [Event("group", "combat.won", {"fighter_id": leader.user_id,
                                              "monster_ids": combat.monster_ids.copy(),
                                              "levels": levels})]
    from .draw import draw_cards
    transition_rng = deepcopy(rng) if rng is not None else Random()
    existing_hand = set(leader.hand)
    result, draw_events = draw_cards(result, leader.user_id, "treasure", treasures,
                                    combat.helper_id is not None, catalog, transition_rng)
    leader = result.players[leader.user_id]
    acquired = [cid for cid in leader.hand if cid not in existing_hand]
    helper_cards = acquired[:combat.help_treasure_count] if combat.helper_id is not None else []
    for cid in helper_cards:
        leader.hand.remove(cid)
        result.players[combat.helper_id].hand.append(cid)
    for event in draw_events:
        if event.name == "card.drawn":
            cid = event.data["card_id"]
            recipient = combat.helper_id if cid in helper_cards else leader.user_id
            events.append(Event(event.audience, "treasure.drawn", {**event.data, "recipient_id": recipient}))
        else:
            events.append(event)
    if combat.helper_id is not None:
        helper = result.players[combat.helper_id]
        for cid in combat.help_item_ids:
            leader.in_play.remove(cid)
            if cid in leader.equipped:
                leader.equipped.remove(cid)
            helper.in_play.append(cid)
        if combat.help_item_ids:
            events.append(Event("group", "help.items_transferred", {"card_ids": combat.help_item_ids.copy()}))
    _discard_combat_cards(result)
    result.combat = None
    result.phase = "game.finished" if leader.level >= 10 or result.phase == "game.finished" else "turn.charity"
    if result.phase == "game.finished":
        events.append(Event("group", "game.won", {"user_id": leader.user_id}))
    if rng is not None:
        rng.setstate(transition_rng.getstate())
    return result, events


def close_reaction(state: GameState, catalog: Catalog, now: datetime,
                   rng: Random | None = None) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    combat = state.combat
    if combat.reaction_deadline is None:
        raise RuleError("no reaction window")
    eligible = set(state.order) - set(combat.fighter_ids)
    if now < combat.reaction_deadline and not eligible.issubset(combat.passes):
        raise RuleError("reaction window is still open")
    if declare_result(state, state.active_user_id, catalog).outcome != "provisional_win":
        raise RuleError("fighters are no longer winning")
    return resolve_rewards(state, catalog, rng)


def begin_escape(state: GameState, actor_id: int,
                 catalog: Catalog) -> tuple[GameState, list[Event]]:
    _require_combat(state)
    if actor_id != state.active_user_id:
        raise RuleError("only active fighter can begin escape")
    if declare_result(state, actor_id, catalog).outcome != "must_run_away":
        raise RuleError("fighters can still win")
    result = deepcopy(state)
    result.phase = "combat.run_away"
    result.combat.escape_pending = {
        (user_id, monster_id) for user_id in result.combat.fighter_ids
        for monster_id in result.combat.monster_ids
    }
    return result, [Event("group", "combat.escape_started", {})]


def escape_modifier(state: GameState, actor_id: int, monster_id: str,
                    catalog: Catalog) -> int:
    return state.players[actor_id].escape_bonus


def _discard_combat_cards(state: GameState) -> None:
    for cid in dict.fromkeys(state.combat.monster_ids + state.combat.played_card_ids + state.combat.modifier_ids):
        (state.door_discard if state.card_decks.get(cid, "door") == "door"
         else state.treasure_discard).append(cid)


def apply_bad_stuff(state: GameState, actor_id: int, monster_id: str,
                    catalog: Catalog) -> tuple[GameState, list[Event]]:
    if state.combat is None or monster_id not in state.combat.monster_ids:
        raise RuleError("unknown combat monster")
    if (actor_id, monster_id) in state.combat.prevented_bad_stuff:
        return deepcopy(state), [Event("group", "bad_stuff.prevented", {"user_id": actor_id})]
    result = deepcopy(state)
    events: list[Event] = []
    for effect in catalog[monster_id].bad_stuff:
        if effect["op"] == "death":
            player = result.players[actor_id]
            persistent = set(player.role_ids + player.race_ids)
            corpse = player.hand + [cid for cid in player.in_play if cid not in persistent]
            result.corpse_hand[actor_id] = set(player.hand)
            player.hand = []
            player.in_play = [cid for cid in player.in_play if cid in persistent]
            player.equipped = []
            player.alive = False
            result.corpse[actor_id] = corpse
            result.corpse_looted_by[actor_id] = set()
            events.append(Event("group", "player.died", {"user_id": actor_id,
                                                      "corpse_count": len(corpse)}))
        else:
            result, effect_events = apply_effects(result, actor_id, [effect], catalog)
            events.extend(effect_events)
    return result, events


def run_away(state: GameState, actor_id: int, monster_id: str, rng: Random,
             catalog: Catalog) -> tuple[GameState, list[Event]]:
    if state.phase != "combat.run_away" or state.combat is None:
        raise RuleError("no escape in progress")
    if (actor_id, monster_id) not in state.combat.escape_pending:
        raise RuleError("escape roll already resolved or invalid")
    result = deepcopy(state)
    die = rng.randint(1, 6)
    escaped = die + escape_modifier(result, actor_id, monster_id, catalog) >= 5
    events = [Event("group", "escape.rolled", {"user_id": actor_id,
                 "monster_id": monster_id, "die": die, "escaped": escaped})]
    result.combat.escape_pending.remove((actor_id, monster_id))
    if not escaped:
        result, bad_events = apply_bad_stuff(result, actor_id, monster_id, catalog)
        events.extend(bad_events)
        if not result.players[actor_id].alive:
            result.combat.escape_pending = {pair for pair in result.combat.escape_pending
                                            if pair[0] != actor_id}
    if not result.combat.escape_pending:
        _discard_combat_cards(result)
        result.combat = None
        result.phase = "turn.charity"
        events.append(Event("group", "combat.escape_finished", {}))
    return result, events


def loot_corpse(state: GameState, actor_id: int, deceased_id: int,
                card_id: str) -> tuple[GameState, list[Event]]:
    if actor_id == deceased_id or actor_id not in state.players:
        raise RuleError("invalid corpse looter")
    if deceased_id not in state.corpse or card_id not in state.corpse[deceased_id]:
        raise RuleError("card is not on corpse")
    if actor_id in state.corpse_looted_by.get(deceased_id, set()):
        raise RuleError("player already looted corpse")
    result = deepcopy(state)
    result.corpse[deceased_id].remove(card_id)
    result.corpse_looted_by[deceased_id].add(actor_id)
    if card_id in result.corpse_hand.get(deceased_id, set()):
        result.players[actor_id].hand.append(card_id)
        result.corpse_hand[deceased_id].remove(card_id)
    else:
        result.players[actor_id].in_play.append(card_id)
    return result, [Event("group", "corpse.looted", {"user_id": actor_id,
                                                   "deceased_id": deceased_id,
                                                   "card_id": card_id})]
