"""Lobby and deterministic initial deal."""

from copy import deepcopy
from random import Random

from .model import Catalog, Event, GameState, Player, RuleError


def new_lobby(game_id: str, group_id: int, host_id: int, catalog: Catalog) -> GameState:
    return GameState(game_id, group_id, host_id, "lobby", None, [], {})


def join(state: GameState, user_id: int) -> tuple[GameState, list[Event]]:
    if state.phase != "lobby":
        raise RuleError("game already started")
    if user_id in state.players:
        raise RuleError("player already joined")
    if len(state.order) >= 6:
        raise RuleError("lobby is full")
    result = deepcopy(state)
    result.players[user_id] = Player(user_id)
    result.order.append(user_id)
    return result, [Event("group", "player.joined", {"user_id": user_id})]


def set_ready(state: GameState, user_id: int, ready: bool) -> tuple[GameState, list[Event]]:
    if state.phase != "lobby" or user_id not in state.players:
        raise RuleError("not a lobby player")
    result = deepcopy(state)
    result.players[user_id].ready = ready
    return result, [Event("group", "player.ready", {"user_id": user_id, "ready": ready})]


def start(state: GameState, actor_id: int, catalog: Catalog, rng: Random) -> tuple[GameState, list[Event]]:
    if state.phase != "lobby":
        raise RuleError("game already started")
    if actor_id != state.host_id:
        raise RuleError("only host can start")
    if not 2 <= len(state.order) <= 6:
        raise RuleError("game requires 2 to 6 players")
    if any(not state.players[user_id].ready for user_id in state.order):
        raise RuleError("all players must be ready")
    doors = [card.id for card in catalog.values() if card.deck == "door"]
    treasures = [card.id for card in catalog.values() if card.deck == "treasure"]
    if len(doors) < 4 * len(state.order) or len(treasures) < 4 * len(state.order):
        raise RuleError("not enough cards for initial deal")
    result = deepcopy(state)
    rng.shuffle(doors)
    rng.shuffle(treasures)
    events: list[Event] = []
    for user_id in result.order:
        hand = [doors.pop() for _ in range(4)] + [treasures.pop() for _ in range(4)]
        result.players[user_id].hand = hand
        events.append(Event(f"user:{user_id}", "hand.dealt", {"card_ids": hand.copy()}))
    result.door_deck = doors
    result.treasure_deck = treasures
    result.active_user_id = rng.choice(result.order)
    result.phase = "turn.prepare"
    result.turn_number = 1
    events.append(Event("group", "game.started", {"active_user_id": result.active_user_id, "order": result.order.copy()}))
    return result, events
