"""Physical cards and mutable state for one isolated match."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


class RuleError(ValueError):
    """The proposed game action violates a rule."""


@dataclass(frozen=True)
class CardDef:
    id: str
    deck: str
    kind: str
    name: str
    value: int = 0
    bonus: int = 0
    slots: str | None = None
    size: str = "small"
    effects: list[dict[str, Any]] = field(default_factory=list)
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CardDef":
        return cls(
            id=data["id"], deck=data["deck"], kind=data["kind"],
            name=data["name"], value=data.get("value", 0),
            bonus=data.get("bonus", 0), slots=data.get("slots"),
            size=data.get("size", "small"), effects=list(data.get("effects", [])),
            tags=tuple(data.get("tags", [])),
        )


Catalog = dict[str, CardDef]


@dataclass
class Player:
    user_id: int
    level: int = 1
    hand: list[str] = field(default_factory=list)
    in_play: list[str] = field(default_factory=list)
    equipped: list[str] = field(default_factory=list)
    ready: bool = False
    role_ids: list[str] = field(default_factory=list)
    race_ids: list[str] = field(default_factory=list)
    alive: bool = True
    strength_bonus: int = 0
    escape_bonus: int = 0


@dataclass
class Trade:
    id: str
    sender_id: int
    receiver_id: int
    offered_ids: list[str]
    requested_ids: list[str]
    expires_at: datetime
    status: str = "pending"


@dataclass
class CombatState:
    fighter_ids: list[int] = field(default_factory=list)
    helper_id: int | None = None
    monster_ids: list[str] = field(default_factory=list)
    modifier_ids: list[str] = field(default_factory=list)
    passes: set[int] = field(default_factory=set)
    reaction_deadline: datetime | None = None
    pending_help: tuple[int, int, list[str]] | None = None
    help_treasure_count: int = 0
    help_item_ids: list[str] = field(default_factory=list)
    escape_pending: set[tuple[int, str]] = field(default_factory=set)
    temporary_strength: dict[int, int] = field(default_factory=dict)
    monster_strength_bonus: int = 0
    prevented_bad_stuff: set[tuple[int, str]] = field(default_factory=set)


@dataclass(frozen=True)
class CombatDecision:
    outcome: Literal["provisional_win", "must_run_away"]


@dataclass
class GameState:
    game_id: str
    group_id: int
    host_id: int
    phase: str
    active_user_id: int | None
    order: list[int]
    players: dict[int, Player]
    door_deck: list[str] = field(default_factory=list)
    treasure_deck: list[str] = field(default_factory=list)
    door_discard: list[str] = field(default_factory=list)
    treasure_discard: list[str] = field(default_factory=list)
    combat: CombatState | None = None
    trades: dict[str, Trade] = field(default_factory=dict)
    processed_requests: set[str] = field(default_factory=set)
    corpse: dict[int, list[str]] = field(default_factory=dict)
    turn_number: int = 0
    card_decks: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Command:
    game_id: str
    actor_id: int
    request_id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    audience: str
    name: str
    data: dict[str, Any] = field(default_factory=dict)
