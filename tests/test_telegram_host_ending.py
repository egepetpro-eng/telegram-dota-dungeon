"""Host ending is a reviewed, group-bound service transition, never a victory."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from dota_dungeon.core.model import CombatState
from dota_dungeon.core.trade import offer_trade
from dota_dungeon.telegram.views import render_view
from test_service_router import NOW, message, playing_fixture, press


def assert_unchanged(actual, before):
    assert actual.state == before.state
    assert (actual.version, actual.status, actual.metadata) == (before.version, before.status, before.metadata)
    assert actual.rng.getstate() == before.rng.getstate()


def group_press(intent, uid, update_id, *, chat=None, chat_type="supergroup"):
    update = press(intent, uid, update_id, chat=chat)
    update["callback_query"]["message"]["chat"]["type"] = chat_type
    return update


def rendered_button(repo, action):
    """Read the delivered Telegram keyboard, then resolve its server intent."""
    assert repo.outbox, "Command must deliver a reviewable confirmation panel"
    panel = repo.outbox[-1]["payload"]
    for row in panel.get("reply_markup", {}).get("inline_keyboard", []):
        for item in row:
            intent = repo.callback(item.get("callback_data"))
            if intent and intent.action == action:
                return intent
    pytest.fail(f"Rendered panel has no {action} button: {panel}")


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
def test_host_command_reviews_then_confirm_archives_without_winner_or_card_changes(paused, chat_type):
    repo, router = playing_fixture()
    state, _ = offer_trade(repo.games["g"].state, 11, 22, ["treasure:2"], [],
                           NOW + timedelta(seconds=120), router.release.catalog, NOW)
    repo.games["g"].state = state
    if paused:
        router.route_update(message(11, -100, "/pause", 1), now=NOW)
    before = repo.get("g")
    command = message(11, -100, "/endgame@DOTA_TEST_BOT", 2, chat_type=chat_type)
    router.route_update(command, now=NOW)
    assert_unchanged(repo.get("g"), before)
    assert repo.outbox, "Host endgame must deliver confirmation before mutation"
    panel = repo.outbox[-1]["payload"]
    assert panel["chat_id"] == -100
    assert "без победителя" in panel["text"]
    assert "нельзя" in panel["text"]
    confirm = rendered_button(repo, "confirm_endgame")
    assert (confirm.actor_id, confirm.chat_id, confirm.game_id, confirm.expected_version) == (11, -100, "g", before.version)
    assert confirm.args == {}
    assert confirm.expires_at == NOW + timedelta(seconds=120)
    count = len(repo.outbox)
    router.route_update(command, now=NOW)
    assert len(repo.outbox) == count
    assert_unchanged(repo.get("g"), before)
    sent = len(repo.outbox)
    when = NOW + timedelta(seconds=17)
    update = group_press(confirm, 11, 3, chat_type=chat_type)
    update["callback_query"]["message"]["date"] = 0
    update["callback_query"]["now"] = "2000-01-01T00:00:00+00:00"
    router.route_update(update, now=when)
    finished = repo.get("g")
    assert (finished.state.phase, finished.status, finished.version) == ("game.finished", "finished", before.version + 1)
    assert finished.metadata["ended_by"] == 11
    assert finished.metadata["ended_at"] == when.isoformat()
    assert finished.state.players == before.state.players
    for zone in ("door_deck", "treasure_deck", "door_discard", "treasure_discard", "corpse"):
        assert getattr(finished.state, zone) == getattr(before.state, zone)
    assert next(iter(finished.state.trades.values())).status == "cancelled"
    assert finished.rng.getstate() == before.rng.getstate()
    endings = repo.outbox[sent:]
    public = [m["payload"].get("text", "") for m in endings if m["payload"].get("chat_id") == -100]
    assert any("Ведущий завершил партию" in text for text in public)
    assert all("Победа" not in text and "🏆" not in text for text in public)
    for outgoing in endings:
        if outgoing["method"] != "answerCallbackQuery":
            assert "Ведущий завершил партию" in outgoing["payload"]["text"]
            assert "reply_markup" not in outgoing["payload"]
    count = len(repo.outbox)
    router.route_update(update, now=when)
    assert len(repo.outbox) == count
    router.route_update(group_press(confirm, 11, 4), now=when)
    assert repo.get("g").version == finished.version
    assert repo.outbox[-1]["method"] == "answerCallbackQuery"
    assert repo.outbox[-1]["payload"]["show_alert"]
    assert repo.active_group(-100) is None
    router.route_update(message(11, -100, "/newgame", 5), now=when)
    assert repo.active_group(-100).state.game_id != "g"
    assert repo.get("g").status == "finished"


@pytest.mark.parametrize("paused", [False, True])
def test_cancel_returns_to_current_group_panel_without_mutation(paused):
    repo, router = playing_fixture()
    if paused:
        router.route_update(message(11, -100, "/pause", 1), now=NOW)
    before = repo.get("g")
    router.route_update(message(11, -100, "/endgame", 2), now=NOW)
    cancel = rendered_button(repo, "cancel_endgame")
    router.route_update(group_press(cancel, 11, 3), now=NOW)
    assert_unchanged(repo.get("g"), before)
    assert repo.outbox[-1]["payload"]["chat_id"] == -100
    assert "без победителя" not in repo.outbox[-1]["payload"]["text"]
    assert rendered_button(repo, "resume" if paused else "pause").actor_id == 11


@pytest.mark.parametrize("uid,chat,chat_type", [
    (22, -100, "supergroup"), (33, -100, "group"), (11, 11, "private"),
    (11, -100, "channel"), (11, -200, "supergroup"),
])
def test_endgame_command_requires_host_and_matching_group(uid, chat, chat_type):
    repo, router = playing_fixture()
    before = repo.get("g")
    router.route_update(message(uid, chat, "/endgame", 1, chat_type=chat_type), now=NOW)
    assert_unchanged(repo.get("g"), before)
    assert not any(c.action == "confirm_endgame" for c in repo.intents.values())


@pytest.mark.parametrize("action", ["confirm_endgame", "cancel_endgame"])
@pytest.mark.parametrize("uid,chat,chat_type,elapsed", [
    (22, -100, "supergroup", 0), (33, -100, "supergroup", 0),
    (11, -200, "supergroup", 0), (11, 11, "private", 0),
    (11, -100, "channel", 0), (11, -100, "supergroup", 120),
])
def test_confirmation_rejects_wrong_actor_chat_type_and_expired_intent(uid, chat, chat_type, elapsed, action):
    repo, router = playing_fixture()
    router.route_update(message(11, -100, "/endgame", 1), now=NOW)
    confirm = rendered_button(repo, action)
    before = repo.get("g")
    router.route_update(group_press(confirm, uid, 2, chat=chat, chat_type=chat_type), now=NOW + timedelta(seconds=elapsed))
    assert_unchanged(repo.get("g"), before)
    assert repo.outbox[-1]["payload"]["show_alert"]


def test_confirmation_also_checks_game_group_when_intent_chat_matches_caller():
    repo, router = playing_fixture()
    router.route_update(message(11, -100, "/endgame", 1), now=NOW)
    confirm = rendered_button(repo, "confirm_endgame")
    # Model an inconsistent persisted intention; intent authorization alone passes.
    foreign = replace(confirm, chat_id=-200)
    repo.intents[foreign.token] = foreign
    before = repo.get("g")
    router.route_update(group_press(foreign, 11, 2), now=NOW)
    assert_unchanged(repo.get("g"), before)
    assert repo.outbox[-1]["payload"]["show_alert"]


def test_confirmation_cannot_end_after_any_version_change():
    repo, router = playing_fixture()
    router.route_update(message(11, -100, "/endgame", 1), now=NOW)
    confirm = rendered_button(repo, "confirm_endgame")
    router.route_update(message(11, -100, "/pause", 2), now=NOW)
    before = repo.get("g")
    router.route_update(group_press(confirm, 11, 3), now=NOW)
    assert_unchanged(repo.get("g"), before)
    assert repo.outbox[-1]["payload"]["show_alert"]


def test_confirm_rechecks_host_even_for_issued_intent():
    repo, router = playing_fixture()
    router.route_update(message(11, -100, "/endgame", 1), now=NOW)
    confirm = rendered_button(repo, "confirm_endgame")
    repo.games["g"].state.host_id = 22
    before = repo.get("g")
    router.route_update(group_press(confirm, 11, 2), now=NOW)
    assert_unchanged(repo.get("g"), before)


def test_host_ending_during_combat_closes_panels_and_keeps_private_pending_data_hidden():
    repo, router = playing_fixture()
    state = repo.games["g"].state
    state.phase = "combat.active"
    state.combat = CombatState(fighter_ids=[11], monster_ids=["door:2"], pending_help=(22, 1, ["treasure:0"]))
    state.players[11].pending_identity_excess = {"role": 1}
    state.players[11].level = 10  # Even a high level must not fabricate a host-end winner.
    before = deepcopy(state)
    router.route_update(message(11, -100, "/endgame", 1), now=NOW)
    assert repo.outbox, "Host endgame must deliver confirmation before mutation"
    panel = repo.outbox[-1]["payload"]
    assert all(router.release.catalog[c].name not in str(panel) for c in ["treasure:0", "door:1"])
    confirm = rendered_button(repo, "confirm_endgame")
    sent = len(repo.outbox)
    router.route_update(group_press(confirm, 11, 2), now=NOW)
    snapshot = repo.get("g")
    assert snapshot.state.combat == before.combat
    assert snapshot.state.players == before.players
    for outgoing in repo.outbox[sent:]:
        payload = outgoing["payload"]
        assert "treasure card" not in str(payload)
        assert "pending_help" not in str(payload)
        assert "pending_identity_excess" not in str(payload)
        assert "reply_markup" not in payload
    for screen in ["group", "main", "hand", "character", "equipment", "trade", "sell", "corpses", "card:treasure:0"]:
        view = router._render(snapshot, 11, screen, NOW)
        assert "Ведущий завершил партию" in view.text
        assert "Победа" not in view.text
        assert not view.rows
        assert view.photo is None


def test_normal_victory_stays_distinct_and_finished_views_have_no_actions():
    repo, router = playing_fixture()
    state = repo.games["g"].state
    state.phase = "game.finished"
    state.players[22].level = 10
    for screen in ["group", "main", "hand", "sell", "corpses"]:
        view = render_view(state, 11, screen, router.release, now=NOW)
        assert "Победа" in view.text and "Игрок 22" in view.text
        assert "Ведущий" not in view.text
        assert not view.rows
