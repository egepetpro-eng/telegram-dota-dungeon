from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def intent(**changes):
    from dota_dungeon.telegram.callbacks import CallbackIntent
    return CallbackIntent("opaque_token_abcdefghijkl", "g1", 3, 11, 11,
                          "play_card", {"card_id": "private"}, NOW + timedelta(minutes=5), **changes)


def test_private_intent_only_authorizes_actual_owner_and_current_version():
    from dota_dungeon.telegram.callbacks import authorize_callback
    result = authorize_callback(intent(), telegram_user_id=11, chat_id=11,
                                now=NOW, current_version=3, member_ids={11, 22},
                                phase="turn.prepare", host_id=11)
    assert result.game_id == "g1"
    assert result.actor_id == 11


@pytest.mark.parametrize("user,chat,version,now,members", [
    (22, 11, 3, NOW, {11, 22}),
    (11, -100, 3, NOW, {11, 22}),
    (11, 11, 4, NOW, {11, 22}),
    (11, 11, 3, NOW + timedelta(hours=1), {11, 22}),
    (11, 11, 3, NOW, {22}),
])
def test_foreign_expired_or_stale_private_intent_rejects(user, chat, version, now, members):
    from dota_dungeon.telegram.callbacks import authorize_callback
    with pytest.raises(ValueError):
        authorize_callback(intent(), telegram_user_id=user, chat_id=chat, now=now,
                           current_version=version, member_ids=members,
                           phase="turn.prepare", host_id=11)


def test_shared_public_token_cannot_become_private_card_action():
    from dota_dungeon.telegram.callbacks import authorize_callback
    unsafe = replace(intent(), actor_id=None, chat_id=-100)
    with pytest.raises(ValueError):
        authorize_callback(unsafe, telegram_user_id=11, chat_id=-100, now=NOW,
                           current_version=3, member_ids={11, 22}, phase="lobby", host_id=11)


def test_shared_join_is_allowed_in_lobby_but_start_requires_host():
    from dota_dungeon.telegram.callbacks import authorize_callback
    join = replace(intent(), actor_id=None, chat_id=-100, action="join", args={})
    assert authorize_callback(join, telegram_user_id=33, chat_id=-100, now=NOW,
                              current_version=3, member_ids={11, 22}, phase="lobby", host_id=11).actor_id is None
    start = replace(join, action="start")
    with pytest.raises(ValueError):
        authorize_callback(start, telegram_user_id=22, chat_id=-100, now=NOW,
                           current_version=3, member_ids={11, 22}, phase="lobby", host_id=11)


def test_generated_callback_fits_api_limit_and_contains_no_command_data():
    from dota_dungeon.telegram.callbacks import new_token
    values = {new_token() for _ in range(50)}
    assert len(values) == 50
    assert all(22 <= len(value.encode()) <= 64 for value in values)
    assert all("private" not in value and "play_card" not in value for value in values)
