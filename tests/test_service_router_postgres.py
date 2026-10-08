"""Exercise router/storage signatures and opaque intention recovery on PostgreSQL."""
import pytest
from test_service_store import repository
from test_service_router import NOW, message, press, release_fixture


def latest(repo, action):
    for outgoing in reversed(repo.pending_outbox()):
        for row in outgoing["payload"].get("reply_markup", {}).get("inline_keyboard", []):
            for item in row:
                if "callback_data" in item:
                    intent = repo.callback(item["callback_data"])
                    if intent.action == action:
                        return intent
    raise AssertionError(f"No {action} button")


def test_router_lobby_and_private_links_survive_repository_reload(repository):
    from dota_dungeon.telegram.router import Router
    from dota_dungeon.service.store import GameRepository
    router = Router(repository, release_fixture(), "dota_test_bot")
    router.route_update(message(11, -100, "/newgame", 1), now=NOW)
    game_id = repository.active_group(-100).state.game_id
    router.route_update(press(latest(repository, "join"), 22, 2), now=NOW)
    for uid in (11, 22):
        router.route_update(message(uid, uid, "/start", uid), now=NOW)
        router.route_update(press(latest(repository, "ready"), uid, uid + 1), now=NOW)
    reloaded = GameRepository(repository.database_url, schema=repository.schema)
    router = Router(reloaded, release_fixture(), "dota_test_bot")
    update = press(latest(reloaded, "start"), 11, 30)
    router.route_update(update, now=NOW)
    before = reloaded.get(game_id)
    count = len(reloaded.pending_outbox())
    router.route_update(update, now=NOW)
    assert reloaded.get(game_id).version == before.version
    assert len(reloaded.pending_outbox()) == count
    assert len(before.state.players[11].hand) == len(before.state.players[22].hand) == 8
    for outgoing in reloaded.pending_outbox():
        if outgoing["payload"].get("chat_id") == -100:
            assert "treasure card" not in str(outgoing["payload"])


@pytest.mark.parametrize("paused", [False, True])
def test_host_confirmation_archives_party_atomically_after_database_reload(repository, paused):
    from dota_dungeon.telegram.router import Router
    from dota_dungeon.service.store import GameRepository
    from dota_dungeon.service.timers import refresh_timers
    repository.scheduler = lambda saved, mutation: refresh_timers(saved, mutation, NOW)
    release = release_fixture()
    router = Router(repository, release, "dota_test_bot")
    router.route_update(message(11, -100, "/newgame", 1), now=NOW)
    game_id = repository.active_group(-100).state.game_id
    router.route_update(press(latest(repository, "join"), 22, 2), now=NOW)
    for uid in (11, 22):
        router.route_update(message(uid, uid, "/start", uid), now=NOW)
        router.route_update(press(latest(repository, "ready"), uid, uid + 1), now=NOW)
    router.route_update(press(latest(repository, "start"), 11, 30), now=NOW)
    if paused:
        router.route_update(message(11, -100, "/pause", 31), now=NOW)
    before = repository.get(game_id)
    router.route_update(message(11, -100, "/endgame", 32), now=NOW)
    assert repository.get(game_id).version == before.version
    confirm = latest(repository, "confirm_endgame")
    restarted = GameRepository(repository.database_url, schema=repository.schema,
                               scheduler=repository.scheduler)
    router = Router(restarted, release, "dota_test_bot")
    update = press(confirm, 11, 33)
    update["callback_query"]["message"]["chat"]["type"] = "supergroup"
    router.route_update(update, now=NOW)
    finished = restarted.get(game_id)
    assert finished.status == "finished" and finished.state.phase == "game.finished"
    assert finished.state.players == before.state.players
    assert finished.version == before.version + 1
    assert restarted.active_group(-100) is None
    assert restarted.active_user(11) == []
    assert not restarted.due_timers(now=NOW)
    with restarted.connection() as connection:
        assert not connection.execute("SELECT 1 FROM game_timers WHERE game_id=%s AND status='pending'",
                                      (game_id,)).fetchall()
        event = connection.execute("SELECT name,data FROM game_events WHERE game_id=%s AND name='game.ended'",
                                   (game_id,)).fetchall()
    assert event == [{"name": "game.ended", "data": {"user_id": 11}}]
    count = len(restarted.pending_outbox())
    router.route_update(update, now=NOW)
    assert len(restarted.pending_outbox()) == count
    assert restarted.get(game_id).version == finished.version
    router.route_update(message(11, -100, "/newgame", 34), now=NOW)
    assert restarted.active_group(-100).state.game_id != game_id
