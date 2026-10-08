"""Atomic exchange of open possessions between players."""

from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from .model import Catalog, Event, GameState, Player, RuleError, Trade
from .items import is_item_card, big_limit, big_count, reconcile_possessions


def _ensure_trade_allowed(state: GameState, actor_id: int, partner_id: int) -> None:
    if actor_id == partner_id or actor_id not in state.players or partner_id not in state.players:
        raise RuleError("invalid trade partner")
    if state.combat is not None or state.phase.startswith("combat."):
        raise RuleError("cannot trade during combat")


def _check_open(player: Player, card_ids: list[str], label: str) -> None:
    if len(card_ids) != len(set(card_ids)):
        raise RuleError("duplicate item")
    if any(cid not in player.in_play for cid in card_ids):
        raise RuleError(f"{label} item must be in play and have unchanged owner")


def offer_trade(
    state: GameState,
    actor_id: int,
    partner_id: int,
    offered_ids: list[str],
    requested_ids: list[str],
    expires_at: datetime,
    catalog: Catalog,
    now: datetime,
) -> tuple[GameState, list[Event]]:
    _ensure_trade_allowed(state, actor_id, partner_id)
    if expires_at <= now or expires_at > now + timedelta(minutes=2):
        raise RuleError("trade must expire within two minutes")
    if not offered_ids and not requested_ids:
        raise RuleError("empty trade")
    _check_open(state.players[actor_id], offered_ids, "offered")
    _check_open(state.players[partner_id], requested_ids, "requested")
    if any(not is_item_card(catalog[cid]) for cid in offered_ids + requested_ids):
        raise RuleError("only items can be traded")
    reserved = {
        cid
        for trade in state.trades.values()
        if trade.status == "pending" and trade.expires_at > now
        for cid in trade.offered_ids + trade.requested_ids
    }
    if reserved.intersection(offered_ids + requested_ids):
        raise RuleError("item already reserved in another trade")
    result = deepcopy(state)
    trade_id = uuid4().hex
    result.trades[trade_id] = Trade(
        trade_id,
        actor_id,
        partner_id,
        offered_ids.copy(),
        requested_ids.copy(),
        expires_at,
    )
    return result, [
        Event(
            f"user:{partner_id}",
            "trade.offered",
            {
                "trade_id": trade_id,
                "offered_ids": offered_ids.copy(),
                "requested_ids": requested_ids.copy(),
            },
        )
    ]


def validate_trade_transfer(
    seller: Player, buyer: Player, trade: Trade, catalog: Catalog
) -> None:
    _check_open(seller, trade.offered_ids, "offered")
    _check_open(buyer, trade.requested_ids, "requested")
    if any(
        not is_item_card(catalog[cid])
        for cid in trade.offered_ids + trade.requested_ids
    ):
        raise RuleError("only items can be traded")
    for player, outgoing, incoming in (
        (seller, trade.offered_ids, trade.requested_ids),
        (buyer, trade.requested_ids, trade.offered_ids),
    ):
        remaining = (set(player.in_play) - set(outgoing)) | set(incoming)
        if big_limit(player, catalog) is not None and big_count(
            player, catalog, remaining
        ) > big_limit(player, catalog):
            raise RuleError("Big item carrying limit")


def transfer_items(sender: Player, receiver: Player, card_ids: list[str]) -> None:
    for cid in card_ids:
        sender.in_play.remove(cid)
        if cid in sender.equipped:
            sender.equipped.remove(cid)
        receiver.in_play.append(cid)


def accept_trade(
    state: GameState, actor_id: int, trade_id: str, catalog: Catalog, now: datetime
) -> tuple[GameState, list[Event]]:
    if trade_id not in state.trades:
        raise RuleError("unknown trade")
    trade = state.trades[trade_id]
    if actor_id != trade.receiver_id:
        raise RuleError("only recipient can accept")
    if trade.status != "pending" or now >= trade.expires_at:
        raise RuleError("trade is no longer available")
    _ensure_trade_allowed(state, trade.sender_id, trade.receiver_id)
    seller = state.players[trade.sender_id]
    buyer = state.players[trade.receiver_id]
    validate_trade_transfer(seller, buyer, trade, catalog)
    result = deepcopy(state)
    saved = result.trades[trade_id]
    transfer_items(
        result.players[saved.sender_id],
        result.players[saved.receiver_id],
        saved.offered_ids,
    )
    transfer_items(
        result.players[saved.receiver_id],
        result.players[saved.sender_id],
        saved.requested_ids,
    )
    reconcile_possessions(result, saved.sender_id, catalog)
    reconcile_possessions(result, saved.receiver_id, catalog)
    saved.status = "accepted"
    return result, [
        Event(
            "group",
            "trade.accepted",
            {
                "trade_id": trade_id,
                "sender_id": saved.sender_id,
                "receiver_id": saved.receiver_id,
                "offered_ids": saved.offered_ids.copy(),
                "requested_ids": saved.requested_ids.copy(),
            },
        )
    ]


def expire_trade(state: GameState, trade_id: str,
                 now: datetime) -> tuple[GameState, list[Event]]:
    if trade_id not in state.trades:
        raise RuleError("unknown trade")
    trade = state.trades[trade_id]
    if trade.status != "pending" or now < trade.expires_at:
        raise RuleError("trade is not ready to expire")
    result = deepcopy(state)
    result.trades[trade_id].status = "expired"
    return result, [Event(f"user:{trade.sender_id}", "trade.expired", {"trade_id": trade_id}),
                    Event(f"user:{trade.receiver_id}", "trade.expired", {"trade_id": trade_id})]


def cancel_trades_for_combat(state: GameState, fighter_id: int) -> list[Event]:
    events = []
    for trade in state.trades.values():
        if trade.status == "pending" and fighter_id in {trade.sender_id, trade.receiver_id}:
            trade.status = "cancelled"
            events.append(Event(f"user:{trade.receiver_id}", "trade.cancelled", {"trade_id": trade.id}))
            events.append(Event(f"user:{trade.sender_id}", "trade.cancelled", {"trade_id": trade.id}))
    return events


def cancel_trades_for_cards(state: GameState, card_ids: list[str]) -> None:
    changed = set(card_ids)
    for trade in state.trades.values():
        if trade.status == "pending" and changed.intersection(trade.offered_ids + trade.requested_ids):
            trade.status = "cancelled"


def cancel_trade(state: GameState, actor_id: int, trade_id: str) -> tuple[GameState, list[Event]]:
    if state.phase not in {"turn.prepare", "turn.after_door", "turn.charity"} or state.combat:
        raise RuleError("cannot cancel trade in this phase")
    offer = state.trades.get(trade_id)
    if actor_id not in state.players or offer is None or actor_id not in {offer.sender_id, offer.receiver_id}:
        raise RuleError("trade is not available to this player")
    if offer.status != "pending":
        raise RuleError("trade is no longer available")
    result = deepcopy(state)
    result.trades[trade_id].status = "cancelled"
    return result, [Event(f"user:{uid}", "trade.cancelled", {"trade_id": trade_id})
                    for uid in (offer.sender_id, offer.receiver_id)]
