"""Replay-safe command boundary for a single game state."""

from collections.abc import Callable
from random import Random

from . import character, combat, items, play, setup, trade, turn, decisions
from .model import Catalog, Command, Event, GameState, RuleError

Handler = Callable[[GameState, Command, Catalog, Random], tuple[GameState, list[Event]]]


def _arg(command: Command, key: str):
    try:
        return command.args[key]
    except KeyError as exc:
        raise RuleError(f"missing argument: {key}") from exc


HANDLERS: dict[str, Handler] = {
    "expire_escape": lambda s, c, catalog, rng: combat.expire_escape(
        s,
        c.actor_id,
        _arg(c, "player_id"),
        _arg(c, "monster_id"),
        _arg(c, "roll_id"),
        catalog,
        rng,
        _arg(c, "now"),
    ),
    "respond_decision": lambda s, c, catalog, rng: decisions.respond_decision(
        s,
        c.actor_id,
        _arg(c, "decision_id"),
        _arg(c, "choices"),
        catalog,
        rng,
        _arg(c, "now"),
    ),
    "expire_decision": lambda s, c, catalog, rng: decisions.respond_decision(
        s,
        c.actor_id,
        _arg(c, "decision_id"),
        {},
        catalog,
        rng,
        _arg(c, "now"),
        expire=True,
    ),
    "monster_action": lambda s, c, catalog, rng: combat.monster_action(
        s,
        c.actor_id,
        _arg(c, "monster_id"),
        _arg(c, "choices"),
        catalog,
        rng,
        _arg(c, "now"),
    ),
    "force_help": lambda s, c, catalog, rng: combat.force_help(
        s, c.actor_id, _arg(c, "helper_id"), catalog, _arg(c, "now")
    ),
    "join_undead": lambda s, c, catalog, rng: combat.join_undead(
        s, c.actor_id, _arg(c, "card_id"), catalog, _arg(c, "now")
    ),
    "use_ability": lambda s, c, catalog, rng: character.use_ability(
        s,
        c.actor_id,
        _arg(c, "ability_key"),
        c.args.get("target", {}),
        _arg(c, "cost_ids"),
        catalog,
        rng,
        _arg(c, "now"),
    ),
    "set_character_sex": lambda s, c, catalog, rng: setup.set_character_sex(
        s, c.actor_id, c.args.get("character_sex")
    ),
    "carry_item": lambda s, c, catalog, rng: items.carry(
        s, c.actor_id, _arg(c, "card_id"), catalog
    ),
    "discard_identity": lambda s, c, catalog, rng: items.discard_identity(
        s, c.actor_id, _arg(c, "card_id"), catalog
    ),
    "assign_hireling": lambda s, c, catalog, rng: items.assign_hireling(
        s, c.actor_id, _arg(c, "hireling_id"), _arg(c, "card_id"), catalog
    ),
    "resolve_identity_excess": lambda s, c, catalog, rng: items.resolve_identity_excess(
        s, c.actor_id, _arg(c, "card_ids"), catalog
    ),
    "resolve_big_items": lambda s, c, catalog, rng: items.resolve_big_items(
        s, c.actor_id, _arg(c, "card_ids"), catalog, c.args.get("recipient_id")
    ),
    "resolve_escape": lambda s, c, catalog, rng: combat.resolve_escape(
        s, c.actor_id, _arg(c, "monster_id"), catalog, rng, c.args.get("now")
    ),
    "play_card": lambda s, c, catalog, rng: play.play_card(
        s,
        c.actor_id,
        _arg(c, "card_id"),
        c.args.get("target", {}),
        catalog,
        rng,
        _arg(c, "now"),
        choices=c.args.get("choices"),
    ),
    "leave_lobby": lambda s, c, catalog, rng: setup.leave_lobby(s, c.actor_id),
    "decline_help": lambda s, c, catalog, rng: combat.decline_help(s, c.actor_id),
    "cancel_trade": lambda s, c, catalog, rng: trade.cancel_trade(
        s, c.actor_id, _arg(c, "trade_id")
    ),
    "join": lambda s, c, catalog, rng: setup.join(s, c.actor_id),
    "ready": lambda s, c, catalog, rng: setup.set_ready(
        s, c.actor_id, _arg(c, "ready")
    ),
    "start": lambda s, c, catalog, rng: setup.start(s, c.actor_id, catalog, rng),
    "open_door": lambda s, c, catalog, rng: turn.open_door(
        s,
        c.actor_id,
        catalog,
        rng,
        resurrection_ids=c.args.get("resurrection_ids"),
        now=c.args.get("now"),
    ),
    "seek_trouble": lambda s, c, catalog, rng: turn.seek_trouble(
        s, c.actor_id, _arg(c, "card_id"), catalog, now=c.args.get("now"), rng=rng
    ),
    "loot_room": lambda s, c, catalog, rng: turn.loot_room(
        s, c.actor_id, rng, catalog=catalog
    ),
    "give_charity": lambda s, c, catalog, rng: turn.give_charity(
        s, c.actor_id, _arg(c, "assignments"), catalog
    ),
    "end_turn": lambda s, c, catalog, rng: turn.end_turn(
        s, c.actor_id, rng, catalog=catalog
    ),
    "equip": lambda s, c, catalog, rng: items.equip(
        s, c.actor_id, _arg(c, "card_id"), catalog
    ),
    "unequip": lambda s, c, catalog, rng: items.unequip(
        s, c.actor_id, _arg(c, "card_id")
    ),
    "play_identity": lambda s, c, catalog, rng: items.play_identity(
        s, c.actor_id, _arg(c, "card_id"), catalog, replace_id=c.args.get("replace_id")
    ),
    "sell": lambda s, c, catalog, rng: items.sell(
        s, c.actor_id, _arg(c, "card_ids"), catalog
    ),
    "offer_trade": lambda s, c, catalog, rng: trade.offer_trade(
        s,
        c.actor_id,
        _arg(c, "partner_id"),
        _arg(c, "offered_ids"),
        _arg(c, "requested_ids"),
        _arg(c, "expires_at"),
        catalog,
        _arg(c, "now"),
    ),
    "accept_trade": lambda s, c, catalog, rng: trade.accept_trade(
        s, c.actor_id, _arg(c, "trade_id"), catalog, _arg(c, "now")
    ),
    "expire_trade": lambda s, c, catalog, rng: trade.expire_trade(
        s, _arg(c, "trade_id"), _arg(c, "now")
    ),
    "ask_help": lambda s, c, catalog, rng: combat.ask_help(
        s,
        c.actor_id,
        _arg(c, "helper_id"),
        _arg(c, "treasure_count"),
        _arg(c, "item_ids"),
        catalog,
    ),
    "accept_help": lambda s, c, catalog, rng: combat.accept_help(
        s, c.actor_id, catalog, now=c.args.get("now"), rng=rng
    ),
    "play_combat_card": lambda s, c, catalog, rng: combat.play_combat_card(
        s, c.actor_id, _arg(c, "card_id"), _arg(c, "target_id"), catalog, _arg(c, "now")
    ),
    "declare_win": lambda s, c, catalog, rng: combat.declare_win(
        s, c.actor_id, catalog, _arg(c, "now"), c.args.get("seconds", 30)
    ),
    "pass_reaction": lambda s, c, catalog, rng: combat.pass_reaction(s, c.actor_id),
    "close_reaction": lambda s, c, catalog, rng: combat.close_reaction(
        s, catalog, _arg(c, "now"), rng, resurrection_ids=c.args.get("resurrection_ids")
    ),
    "begin_escape": lambda s, c, catalog, rng: combat.begin_escape(
        s, c.actor_id, catalog
    ),
    "run_away": lambda s, c, catalog, rng: combat.run_away(
        s, c.actor_id, _arg(c, "monster_id"), rng, catalog, now=c.args.get("now")
    ),
    "loot_corpse": lambda s, c, catalog, rng: combat.loot_corpse(
        s, c.actor_id, _arg(c, "deceased_id"), _arg(c, "card_id")
    ),
}


ACTIVE_PLAYER_COMMANDS = {
    "open_door",
    "seek_trouble",
    "loot_room",
    "give_charity",
    "end_turn",
    "sell",
    "ask_help",
    "declare_win",
    "begin_escape",
}


def dispatch(
    state: GameState, command: Command, catalog: Catalog, rng: Random
) -> tuple[GameState, list[Event]]:
    if state.pending_decision and command.name not in {
        "respond_decision",
        "expire_decision",
    }:
        card = catalog.get(command.args.get("card_id"))
        allowed = {
            "curse_response": {"wishing_ring", "wand_of_dowsing"},
            "die_response": {"loaded_die"},
        }.get(state.pending_decision.kind, set())
        if command.name != "play_card" or not card or card.rule_key not in allowed:
            raise RuleError("resolve pending decision first")
    if command.name == "close_reaction" and "resurrection_ids" in command.args:
        selections = command.args["resurrection_ids"]
        if not isinstance(selections, dict) or set(selections) - {command.actor_id}:
            raise RuleError("cannot choose another player resurrection cost")
    target = command.args.get("target", {})
    rule_key = None
    if command.name == "use_ability":
        rule_key = character.ALIASES.get(
            command.args.get("ability_key"), command.args.get("ability_key")
        )
    elif command.name == "play_card" and command.args.get("card_id") in catalog:
        rule_key = catalog[command.args["card_id"]].rule_key
    elif command.name == "resolve_escape":
        target = {"monster_id": command.args.get("monster_id")}
    combat.validate_escape_action(
        state, command.actor_id, command.name, target, catalog, rule_key=rule_key
    )
    actor = state.players.get(command.actor_id)
    choices = {"resolve_big_items", "resolve_identity_excess"}
    pending = any(
        p.pending_identity_excess or p.pending_big_excess
        for p in state.players.values()
    )
    sale_resolution = (
        actor is not None
        and actor.pending_big_excess
        and not actor.pending_identity_excess
        and command.name == "sell"
    )
    if (
        pending
        and command.name not in choices | {"resolve_escape"}
        and not sale_resolution
    ):
        raise RuleError("resolve mandatory excess choices first")
    if command.name == "close_reaction" and command.actor_id not in {
        state.active_user_id,
        combat.leader_id(state),
    }:
        raise RuleError(
            "not your turn: only combat leader or original turn timer can close reaction"
        )
    handler = HANDLERS.get(command.name)
    if handler is None:
        raise RuleError("unknown command")
    if command.name in ACTIVE_PLAYER_COMMANDS and command.actor_id != (
        combat.leader_id(state)
        if command.name in {"ask_help", "declare_win", "begin_escape"}
        else state.active_user_id
    ):
        raise RuleError("not your turn")
    if command.name == "play_identity" and command.actor_id != (
        combat.leader_id(state)
        if command.name in {"ask_help", "declare_win", "begin_escape"}
        else state.active_user_id
    ):
        if state.phase != "turn.prepare" or state.turn_number > 1:
            raise RuleError("not your turn")
    result, events = handler(state, command, catalog, rng)
    if (
        result.combat
        and result.phase == "combat.active"
        and not result.pending_decision
        and not result.combat.reward_state
    ):
        result, mandatory = combat.settle_mandatory_monsters(
            result, catalog, rng, command.args.get("now")
        )
        events.extend(mandatory)
    return result, events


def decide(
    state: GameState, command: Command, catalog: Catalog, rng: Random
) -> tuple[GameState, list[Event]]:
    if command.game_id != state.game_id:
        raise RuleError("command belongs to another game")
    if not command.request_id:
        raise RuleError("request id is required")
    if command.request_id in state.processed_requests:
        return state, []
    from copy import deepcopy

    transition_rng = deepcopy(rng)
    configured = command.args.get("reaction_seconds")
    transition_state = deepcopy(state)
    if configured is not None:
        if type(configured) is not int or configured not in {15, 30, 60}:
            raise RuleError("invalid reaction duration")
        if transition_state.combat:
            transition_state.combat.reaction_seconds = configured
    result, events = dispatch(transition_state, command, catalog, transition_rng)
    if configured is not None and result.combat:
        result.combat.reaction_seconds = configured
    rng.setstate(transition_rng.getstate())
    result.processed_requests.add(command.request_id)
    return result, events
