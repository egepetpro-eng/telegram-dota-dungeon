"""Exercise router/storage signatures and opaque intention recovery on PostgreSQL."""
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
