"""Opaque server-side intentions: a copied button grants no extra authority."""
from dataclasses import dataclass
from datetime import datetime
import secrets


@dataclass(frozen=True)
class CallbackIntent:
    token: str
    game_id: str
    expected_version: int
    actor_id: int | None
    chat_id: int
    action: str
    args: dict
    expires_at: datetime


def new_token() -> str:
    return secrets.token_urlsafe(18)


def authorize_callback(intent: CallbackIntent, *, telegram_user_id: int, chat_id: int,
                       now: datetime, current_version: int, member_ids: set[int],
                       phase: str, host_id: int) -> CallbackIntent:
    if type(telegram_user_id) is not int or type(chat_id) is not int:
        raise ValueError("invalid Telegram identity")
    if now.utcoffset() is None or intent.expires_at.utcoffset() is None:
        raise ValueError("deadline requires timezone")
    if now >= intent.expires_at:
        raise ValueError("button expired")
    if current_version != intent.expected_version:
        raise ValueError("button is stale")
    if chat_id != intent.chat_id:
        raise ValueError("button belongs to another chat")
    if intent.actor_id is not None:
        if telegram_user_id != intent.actor_id or telegram_user_id not in member_ids:
            raise ValueError("button belongs to another player")
    elif intent.action == "inspect_card":
        if telegram_user_id not in member_ids:
            raise ValueError("not a game member")
    else:
        if phase != "lobby" or intent.action not in {"join", "ready", "leave_lobby", "start", "refresh_lobby"}:
            raise ValueError("shared button cannot authorize this action")
        if intent.action != "join" and telegram_user_id not in member_ids:
            raise ValueError("not a member of this lobby")
        if intent.action == "start" and telegram_user_id != host_id:
            raise ValueError("only the host may start")
    return intent
