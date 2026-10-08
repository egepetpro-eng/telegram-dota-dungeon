"""Replay-safe command boundary for a single game state."""

from collections.abc import Callable
from random import Random

from . import combat, items, play, setup, trade, turn
from .model import Catalog, Command, Event, GameState, RuleError


Handler = Callable[[GameState, Command, Catalog, Random], tuple[GameState, list[Event]]]


def _arg(command: Command, key: str):
    try:
        return command.args[key]
    except KeyError as exc:
        raise RuleError(f"missing argument: {key}") from exc


HANDLERS: dict[str, Handler] = {
    "play_card": lambda s, c, catalog, rng: play.play_card(
        s, c.actor_id, _arg(c, "card_id"), c.args.get("target", {}), catalog, rng, _arg(c, "now")),
    "leave_lobby": lambda s, c, catalog, rng: setup.leave_lobby(s, c.actor_id),
    "decline_help": lambda s, c, catalog, rng: combat.decline_help(s, c.actor_id),
    "cancel_trade": lambda s, c, catalog, rng: trade.cancel_trade(s, c.actor_id, _arg(c, "trade_id")),
    "join": lambda s, c, catalog, rng: setup.join(s, c.actor_id),
    "ready": lambda s, c, catalog, rng: setup.set_ready(s, c.actor_id, _arg(c, "ready")),
    "start": lambda s, c, catalog, rng: setup.start(s, c.actor_id, catalog, rng),
    "open_door": lambda s, c, catalog, rng: turn.open_door(s, c.actor_id, catalog, rng),
    "seek_trouble": lambda s, c, catalog, rng: turn.seek_trouble(s, c.actor_id, _arg(c, "card_id"), catalog),
    "loot_room": lambda s, c, catalog, rng: turn.loot_room(s, c.actor_id, rng, catalog=catalog),
    "give_charity": lambda s, c, catalog, rng: turn.give_charity(s, c.actor_id, _arg(c, "assignments")),
    "end_turn": lambda s, c, catalog, rng: turn.end_turn(s, c.actor_id, rng, catalog=catalog),
    "equip": lambda s, c, catalog, rng: items.equip(s, c.actor_id, _arg(c, "card_id"), catalog),
    "unequip": lambda s, c, catalog, rng: items.unequip(s, c.actor_id, _arg(c, "card_id")),
    "play_identity": lambda s, c, catalog, rng: items.play_identity(s, c.actor_id, _arg(c, "card_id"), catalog),
    "sell": lambda s, c, catalog, rng: items.sell(s, c.actor_id, _arg(c, "card_ids"), catalog),
    "offer_trade": lambda s, c, catalog, rng: trade.offer_trade(
        s, c.actor_id, _arg(c, "partner_id"), _arg(c, "offered_ids"),
        _arg(c, "requested_ids"), _arg(c, "expires_at"), catalog, _arg(c, "now")),
    "accept_trade": lambda s, c, catalog, rng: trade.accept_trade(
        s, c.actor_id, _arg(c, "trade_id"), catalog, _arg(c, "now")),
    "expire_trade": lambda s, c, catalog, rng: trade.expire_trade(
        s, _arg(c, "trade_id"), _arg(c, "now")),
    "ask_help": lambda s, c, catalog, rng: combat.ask_help(
        s, c.actor_id, _arg(c, "helper_id"), _arg(c, "treasure_count"), _arg(c, "item_ids"), catalog),
    "accept_help": lambda s, c, catalog, rng: combat.accept_help(s, c.actor_id),
    "play_combat_card": lambda s, c, catalog, rng: combat.play_combat_card(
        s, c.actor_id, _arg(c, "card_id"), _arg(c, "target_id"), catalog, _arg(c, "now")),
    "declare_win": lambda s, c, catalog, rng: combat.declare_win(
        s, c.actor_id, catalog, _arg(c, "now"), c.args.get("seconds", 30)),
    "pass_reaction": lambda s, c, catalog, rng: combat.pass_reaction(s, c.actor_id),
    "close_reaction": lambda s, c, catalog, rng: combat.close_reaction(
        s, catalog, _arg(c, "now"), rng),
    "begin_escape": lambda s, c, catalog, rng: combat.begin_escape(s, c.actor_id, catalog),
    "run_away": lambda s, c, catalog, rng: combat.run_away(
        s, c.actor_id, _arg(c, "monster_id"), rng, catalog),
    "loot_corpse": lambda s, c, catalog, rng: combat.loot_corpse(
        s, c.actor_id, _arg(c, "deceased_id"), _arg(c, "card_id")),
}


ACTIVE_PLAYER_COMMANDS = {
    "open_door", "seek_trouble", "loot_room", "give_charity", "end_turn",
    "sell", "ask_help", "declare_win",
    "close_reaction", "begin_escape",
}


def dispatch(state: GameState, command: Command, catalog: Catalog,
             rng: Random) -> tuple[GameState, list[Event]]:
    handler = HANDLERS.get(command.name)
    if handler is None:
        raise RuleError("unknown command")
    if command.name in ACTIVE_PLAYER_COMMANDS and command.actor_id != state.active_user_id:
        raise RuleError("not your turn")
    if command.name in {"equip", "unequip", "play_identity"} and command.actor_id != state.active_user_id:
        if state.phase != "turn.prepare" or state.turn_number > 1:
            raise RuleError("not your turn")
    return handler(state, command, catalog, rng)


def decide(state: GameState, command: Command, catalog: Catalog,
           rng: Random) -> tuple[GameState, list[Event]]:
    if command.game_id != state.game_id:
        raise RuleError("command belongs to another game")
    if not command.request_id:
        raise RuleError("request id is required")
    if command.request_id in state.processed_requests:
        return state, []
    result, events = dispatch(state, command, catalog, rng)
    result.processed_requests.add(command.request_id)
    return result, events
