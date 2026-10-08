"""Lobby and deterministic initial deal."""

from copy import deepcopy
from random import Random

from .draw import draw_cards, resolve_initial_deal
from .model import Catalog, Event, GameState, Player, RuleError


def new_lobby(game_id: str, group_id: int, host_id: int, catalog: Catalog) -> GameState:
    state = GameState(game_id, group_id, host_id, "lobby", None, [], {})
    state.door_deck = [card.id for card in catalog.values() if card.deck == "door"]
    state.treasure_deck = [card.id for card in catalog.values() if card.deck == "treasure"]
    state.card_decks = {card.id: card.deck for card in catalog.values()}
    return state


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


def leave_lobby(state: GameState, actor_id: int) -> tuple[GameState, list[Event]]:
    if state.phase != "lobby" or actor_id not in state.players:
        raise RuleError("not a lobby player")
    if actor_id == state.host_id:
        raise RuleError("host cannot leave own lobby")
    result = deepcopy(state)
    del result.players[actor_id]
    result.order.remove(actor_id)
    return result, [Event("group", "player.left", {"user_id": actor_id})]


def start(
    state: GameState, actor_id: int, catalog: Catalog, rng: Random
) -> tuple[GameState, list[Event]]:
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
    transition_rng = deepcopy(rng)
    result.card_decks = {card.id: card.deck for card in catalog.values()}
    transition_rng.shuffle(doors)
    transition_rng.shuffle(treasures)
    result.door_deck = doors
    result.treasure_deck = treasures
    events: list[Event] = []
    for user_id in result.order:
        for deck in ("door", "treasure"):
            result, drawn_events = draw_cards(
                result, user_id, deck, 4, False, catalog, transition_rng
            )
            events.extend(drawn_events)
        events.append(
            Event(
                f"user:{user_id}",
                "hand.dealt",
                {"card_ids": result.players[user_id].hand.copy()},
            )
        )
    result.active_user_id = transition_rng.choice(result.order)
    for user_id in result.order:
        if result.players[user_id].character_sex is None:
            result.players[user_id].character_sex = transition_rng.choice(
                ("male", "female")
            )
    result.phase = "turn.prepare"
    result.turn_number = 1
    result, trigger_events = resolve_initial_deal(result, catalog, transition_rng)
    events.extend(trigger_events)
    events.append(
        Event(
            "group",
            "game.started",
            {"active_user_id": result.active_user_id, "order": result.order.copy()},
        )
    )
    rng.setstate(transition_rng.getstate())
    return result, events


def set_character_sex(state: GameState, actor_id: int, character_sex: str | None):
    if state.phase != "lobby" or actor_id not in state.players:
        raise RuleError("not a lobby player")
    if character_sex is not None and character_sex not in {"male", "female"}:
        raise RuleError("invalid character sex")
    result = deepcopy(state)
    result.players[actor_id].character_sex = character_sex
    return result, [
        Event(
            "group",
            "character.sex_set",
            {"user_id": actor_id, "character_sex": character_sex},
        )
    ]
