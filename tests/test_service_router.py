"""Adapter scenarios use the real engine with an in-memory durable boundary."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from random import Random
from types import SimpleNamespace

import pytest

from dota_dungeon.core.model import CardDef
from dota_dungeon.service.store import ActiveGameExists, Snapshot, StaleAction, TransactionResult

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


class MemoryRepository:
    def __init__(self):
        self.games, self.links, self.intents = {}, {}, {}
        self.receipts, self.outbox = set(), []

    def create(self, state, rng, metadata=None, *, update_id=None, messages=(), callbacks=()):
        if update_id in self.receipts:
            return False
        if self.active_group(state.group_id):
            raise ActiveGameExists()
        self.games[state.game_id] = Snapshot(deepcopy(state), deepcopy(rng), 0, metadata or {})
        return self.enqueue(update_id, messages, callbacks=callbacks, game_id=state.game_id)

    def get(self, game_id):
        return deepcopy(self.games[game_id])

    def active_group(self, group_id):
        return next((deepcopy(s) for s in self.games.values() if s.state.group_id == group_id and s.state.phase != "game.finished"), None)

    def active_user(self, uid):
        return [deepcopy(s) for s in self.games.values() if uid in s.state.players and s.state.phase != "game.finished"]

    def link_private(self, user_id, chat_id):
        self.links[user_id] = chat_id

    def unavailable_private(self, user_id):
        self.links.pop(user_id, None)

    def private_chat(self, user_id):
        return self.links.get(user_id)

    def callback(self, token):
        return self.intents.get(token)

    def update_seen(self, update_id):
        return update_id in self.receipts

    def enqueue(self, update_id, messages, *, callbacks=(), game_id=None, private_link=None):
        if update_id in self.receipts:
            return False
        self.receipts.add(update_id)
        if private_link:
            self.link_private(*private_link)
        self.outbox.extend(deepcopy(messages))
        self.intents.update({c.token: c for c in callbacks})
        return True

    def apply(self, game_id, expected_version, update_id, transition, **kwargs):
        snapshot = self.get(game_id)
        if update_id in self.receipts:
            return TransactionResult(snapshot, True)
        if expected_version != snapshot.version:
            raise StaleAction()
        if snapshot.status == "paused" and not kwargs.get("allow_paused"):
            raise ValueError("game paused")
        mutation = transition(snapshot)
        result = Snapshot(mutation.state, mutation.rng, snapshot.version + 1,
                          mutation.metadata or snapshot.metadata, mutation.status or snapshot.status)
        self.games[game_id] = deepcopy(result)
        self.enqueue(update_id, mutation.messages, callbacks=getattr(mutation, "callbacks", []), game_id=game_id)
        return TransactionResult(result)


def release_fixture():
    catalog = {}
    for deck in ("door", "treasure"):
        for i in range(32):
            cid = f"{deck}:{i}"
            kind = "race" if deck == "door" else "item"
            catalog[cid] = CardDef(cid, deck, kind, f"{deck} card {i}", value=500 if deck == "treasure" else 0)
    return SimpleNamespace(catalog=catalog, presentations={}, version="synthetic-router", digest="a" * 64)


def message(uid, chat, text, update_id, chat_type=None):
    return {"update_id": update_id, "message": {"from": {"id": uid, "first_name": f"Player {uid}"},
            "chat": {"id": chat, "type": chat_type or ("private" if chat > 0 else "supergroup")}, "text": text}}


def press(intent, uid, update_id, *, chat=None):
    return {"update_id": update_id, "callback_query": {"id": f"q{update_id}", "from": {"id": uid},
            "message": {"chat": {"id": intent.chat_id if chat is None else chat}}, "data": intent.token}}


def button(repo, action, *, actor=None, game=None, **args):
    candidates = [c for c in repo.intents.values() if c.action == action
                  and (actor is None or c.actor_id == actor) and (game is None or c.game_id == game)
                  and all(c.args.get(k) == v for k, v in args.items())]
    return candidates[-1]


def setup_router():
    from dota_dungeon.telegram.router import Router
    repo = MemoryRepository()
    return repo, Router(repo, release_fixture(), "dota_test_bot")


def test_lobby_private_guard_two_player_start_and_duplicate_update():
    repo, router = setup_router()
    router.route_update(message(11, -100, "/newgame", 1), now=NOW)
    game = repo.active_group(-100).state.game_id
    router.route_update(press(button(repo, "join"), 22, 2), now=NOW)
    router.route_update(press(button(repo, "ready"), 11, 3), now=NOW)
    assert not repo.get(game).state.players[11].ready
    assert "лич" in repo.outbox[-1]["payload"].get("text", "").lower()
    for uid, seq in ((11, 10), (22, 20)):
        router.route_update(message(uid, uid, "/start", seq), now=NOW)
        router.route_update(press(button(repo, "ready"), uid, seq + 1), now=NOW)
    ready = repo.get(game)
    router.route_update(press(button(repo, "start"), 22, 30), now=NOW)
    assert repo.get(game).version == ready.version
    update = press(button(repo, "start"), 11, 31)
    router.route_update(update, now=NOW)
    started = repo.get(game)
    assert started.state.phase == "turn.prepare"
    assert len(started.state.players[11].hand) == len(started.state.players[22].hand) == 8
    outgoing = len(repo.outbox)
    router.route_update(update, now=NOW)
    assert repo.get(game).version == started.version
    assert len(repo.outbox) == outgoing
    group_text = " ".join(m["payload"].get("text", "") for m in repo.outbox if m["payload"].get("chat_id") == -100)
    assert "treasure card" not in group_text


def test_private_navigation_is_game_scoped_and_rejects_copied_stale_expired_buttons():
    repo, router = setup_router()
    router.route_update(message(11, 11, "/start", 1), now=NOW)
    for group, seq in ((-100, 10), (-200, 20)):
        router.route_update(message(11, group, "/newgame", seq), now=NOW)
    router.route_update(message(11, 11, "/games", 30), now=NOW)
    choices = [c for c in repo.intents.values() if c.action == "nav" and c.chat_id == 11 and c.args.get("screen") == "main"]
    assert {c.game_id for c in choices} == set(repo.games)
    choice = choices[-1]
    version = repo.get(choice.game_id).version
    router.route_update(press(choice, 11, 31), now=NOW)
    assert repo.get(choice.game_id).version == version
    private_count = len([m for m in repo.outbox if m["payload"].get("chat_id") == 11])
    for uid, chat, when, seq in ((22, 11, NOW, 32), (11, -100, NOW, 33), (11, 11, NOW + timedelta(seconds=121), 34)):
        router.route_update(press(choice, uid, seq, chat=chat), now=when)
    assert len([m for m in repo.outbox if m["payload"].get("chat_id") == 11]) == private_count
    assert repo.get(choice.game_id).version == version


def test_newgame_filters_other_bots_and_enforces_one_active_game_and_six_player_cap():
    repo, router = setup_router()
    router.route_update(message(11, -100, "/newgame@another_bot", 1), now=NOW)
    assert not repo.games
    router.route_update(message(11, -100, "/newgame@DOTA_TEST_BOT", 2), now=NOW)
    router.route_update(message(22, -100, "/newgame", 3), now=NOW)
    assert len(repo.games) == 1
    for uid in range(22, 28):
        router.route_update(press(button(repo, "join"), uid, uid), now=NOW)
    assert len(repo.active_group(-100).state.players) == 6
    assert 27 not in repo.active_group(-100).state.players


def test_group_callback_data_is_opaque_and_all_intents_expire_at_trusted_deadline():
    repo, router = setup_router()
    router.route_update(message(11, -100, "/newgame", 1), now=NOW)
    for intent in repo.intents.values():
        assert len(intent.token.encode()) <= 64
        assert intent.expires_at == NOW + timedelta(seconds=120)
        assert intent.action not in intent.token
    assert "callback_data" in str(repo.outbox)


def playing_fixture():
    from dota_dungeon.core.model import GameState, Player
    repo, router = setup_router()
    release = router.release
    state = GameState("g", -100, 11, "turn.prepare", 11, [11, 22], {
        11: Player(11, hand=["treasure:0", "treasure:1", "door:0"], in_play=["treasure:2"]),
        22: Player(22, hand=["door:1"], in_play=["treasure:3"]),
    }, card_decks={cid: card.deck for cid, card in release.catalog.items()},
        door_deck=["door:2"], treasure_deck=["treasure:4"])
    state.catalog_version, state.catalog_digest = release.version, release.digest
    repo.create(state, Random(0))
    repo.link_private(11, 11)
    repo.link_private(22, 22)
    return repo, router


def test_sale_selection_cancellation_does_not_commit_and_confirmation_uses_core():
    repo, router = playing_fixture()
    router.route_update(message(11, 11, "/prices", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="sell"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, selected=["treasure:0"]), 11, 3), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, selected=["treasure:0", "treasure:1"]), 11, 4), now=NOW)
    confirmation = button(repo, "sell", actor=11)
    router.route_update(press(button(repo, "nav", actor=11, screen="main"), 11, 5), now=NOW)
    assert repo.get("g").version == 0
    assert len(repo.get("g").state.players[11].hand) == 3
    router.route_update(press(confirmation, 11, 6), now=NOW)
    assert repo.get("g").state.players[11].level == 2
    assert repo.get("g").state.players[11].hand == ["door:0"]
    assert set(repo.get("g").state.treasure_discard) == {"treasure:0", "treasure:1"}


def test_trade_composition_and_recipient_acceptance_atomically_swap_open_items():
    repo, router = playing_fixture()
    router.route_update(message(11, 11, "/trade", 1), now=NOW)
    router.route_update(press(button(repo, "trade_partner", actor=11, partner_id=22), 11, 2), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, offered_ids=["treasure:2"]), 11, 3), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, offered_ids=["treasure:2"], requested_ids=["treasure:3"]), 11, 4), now=NOW)
    offer = button(repo, "offer_trade", actor=11)
    assert "expires_at" not in offer.args and "now" not in offer.args
    router.route_update(press(offer, 11, 5), now=NOW)
    trade = next(iter(repo.get("g").state.trades.values()))
    assert trade.expires_at == NOW + timedelta(seconds=120)
    acceptance = button(repo, "accept_trade", actor=22)
    router.route_update(press(acceptance, 11, 6), now=NOW)
    assert repo.get("g").version == 1
    router.route_update(press(acceptance, 22, 7), now=NOW)
    assert repo.get("g").state.players[11].in_play == ["treasure:3"]
    assert repo.get("g").state.players[22].in_play == ["treasure:2"]
    router.route_update(press(acceptance, 22, 8), now=NOW)
    assert repo.get("g").version == 2


def test_identity_card_and_help_terms_are_playable_from_private_menus():
    from dota_dungeon.core.model import CombatState
    repo, router = playing_fixture()
    router.route_update(message(11, 11, "/hand", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="card:door:0"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "choose_card_target", actor=11, card_id="door:0"), 11, 3), now=NOW)
    router.route_update(press(button(repo, "play_identity", actor=11), 11, 4), now=NOW)
    assert repo.get("g").state.players[11].race_ids == ["door:0"]
    snapshot = repo.games["g"]
    snapshot.state.phase = "combat.active"
    snapshot.state.combat = CombatState(fighter_ids=[11], monster_ids=["enemy"])
    router.release.catalog["enemy"] = CardDef("enemy", "door", "monster", "Enemy", bonus=15, treasures=3)
    router.route_update(message(11, 11, "/game", 5), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, flow="help"), 11, 6), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, helper_id=22), 11, 7), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, helper_id=22, treasure_count=2), 11, 8), now=NOW)
    router.route_update(press(button(repo, "ask_help", actor=11, treasure_count=2), 11, 9), now=NOW)
    assert repo.get("g").state.combat.pending_help == (22, 2, [])
    assert any("Сокровищ: 2" in m["payload"].get("text", "") for m in repo.outbox if m["payload"].get("chat_id") == 22)
    router.route_update(press(button(repo, "accept_help", actor=22), 22, 10), now=NOW)
    assert repo.get("g").state.combat.fighter_ids == [11, 22]


def test_host_pause_resume_preserves_game_and_rejects_other_players():
    repo, router = playing_fixture()
    router.route_update(message(22, -100, "/pause", 1), now=NOW)
    assert repo.get("g").status == "active"
    router.route_update(message(11, -100, "/pause", 2), now=NOW)
    assert repo.get("g").status == "paused"
    assert repo.get("g").state.players[11].hand == ["treasure:0", "treasure:1", "door:0"]
    router.route_update(message(11, -100, "/game", 3), now=NOW)
    assert "пауз" in repo.outbox[-1]["payload"]["text"].lower()
    router.route_update(press(button(repo, "resume", actor=11), 22, 4), now=NOW)
    assert repo.get("g").status == "paused"
    router.route_update(message(11, -100, "/resume", 5), now=NOW + timedelta(seconds=30))
    assert repo.get("g").status == "active"


def test_host_configures_reaction_before_start_and_unavailable_private_blocks_ready():
    repo, router = setup_router()
    router.route_update(message(11, -100, "/newgame", 1), now=NOW)
    choice = button(repo, "reaction_seconds", actor=11, seconds=15)
    router.route_update(press(choice, 22, 2), now=NOW)
    assert repo.active_group(-100).metadata["reaction_seconds"] == 30
    router.route_update(press(choice, 11, 3), now=NOW)
    assert repo.active_group(-100).metadata["reaction_seconds"] == 15
    router.route_update(message(11, 11, "/start", 4), now=NOW)
    repo.unavailable_private(11)
    router.route_update(press(button(repo, "ready"), 11, 5), now=NOW)
    assert not repo.active_group(-100).state.players[11].ready


def test_verified_media_binding_renders_only_owners_card_and_public_door_as_photo():
    from dota_dungeon.core.model import CardDef
    repo, router = playing_fixture()
    release = router.release
    release.catalog["door:2"] = CardDef("door:2", "door", "monster", "Public Enemy", rule_key="monster", bonus=10)
    release.catalog["treasure:0"] = CardDef("treasure:0", "treasure", "item", "Private Item", rule_key="item", value=500)
    router.media = {"catalog_version": release.version, "catalog_digest": release.digest,
                    "bindings": {"monster": "portrait", "item": "icon"}, "assets": {
                        "portrait": {"image_url": "https://example.test/monster.png", "status": "verified"},
                        "icon": {"image_url": "https://example.test/item.png", "status": "verified"}}}
    router.route_update(message(11, 11, "/hand", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="card:treasure:0"), 11, 2), now=NOW)
    photo = next(m for m in repo.outbox if m["method"] == "sendPhoto")
    assert photo["payload"]["photo"] == "https://example.test/item.png"
    assert photo["payload"]["chat_id"] == 11
    router.route_update(message(11, -100, "/game", 3), now=NOW)
    router.route_update(press(button(repo, "open_door", actor=11), 11, 4), now=NOW)
    assert any(m["method"] == "sendPhoto" and m["payload"].get("chat_id") == -100
               and m["payload"]["photo"] == "https://example.test/monster.png" for m in repo.outbox)
    assert not any(m["method"] == "sendPhoto" and m["payload"].get("chat_id") == -100
                   and m["payload"]["photo"] == "https://example.test/item.png" for m in repo.outbox)


def test_private_start_replay_cannot_restore_link_marked_unavailable():
    repo, router = setup_router()
    start = message(11, 11, "/start", 1)
    router.route_update(start, now=NOW)
    repo.unavailable_private(11)
    router.route_update(start, now=NOW)
    assert repo.private_chat(11) is None
    router.route_update(message(11, 11, "/start", 2), now=NOW)
    assert repo.private_chat(11) == 11


def test_lobby_leave_decline_help_and_cancel_trade_use_core_lifecycle():
    from dota_dungeon.core.model import CombatState
    repo, router = setup_router()
    router.route_update(message(11, -100, "/newgame", 1), now=NOW)
    router.route_update(press(button(repo, "join"), 22, 2), now=NOW)
    router.route_update(press(button(repo, "leave_lobby"), 22, 3), now=NOW)
    assert repo.active_group(-100).state.order == [11]
    repo, router = playing_fixture()
    state = repo.games["g"].state
    state.phase = "combat.active"
    state.combat = CombatState(fighter_ids=[11], monster_ids=["enemy"], pending_help=(22, 1, []))
    router.release.catalog["enemy"] = CardDef("enemy", "door", "monster", "Enemy", bonus=10, treasures=2)
    router.route_update(message(22, 22, "/game", 1), now=NOW)
    router.route_update(press(button(repo, "decline_help", actor=22), 22, 2), now=NOW)
    assert repo.get("g").state.combat.pending_help is None
    repo.games["g"].state.combat = None
    repo.games["g"].state.phase = "turn.prepare"
    from dota_dungeon.core.trade import offer_trade
    state, _ = offer_trade(repo.games["g"].state, 11, 22, ["treasure:2"], [], NOW + timedelta(seconds=120), router.release.catalog, NOW)
    repo.games["g"].state = state
    router.route_update(message(22, 22, "/game", 3), now=NOW)
    router.route_update(press(button(repo, "cancel_trade", actor=22), 22, 4), now=NOW)
    assert next(iter(repo.get("g").state.trades.values())).status == "cancelled"
    assert repo.get("g").state.players[11].in_play == ["treasure:2"]


def test_two_player_door_loot_charity_end_turn_and_actor_scoped_escape():
    from dota_dungeon.core.model import CombatState
    repo, router = playing_fixture()
    repo.games["g"].state.door_deck = ["door:3", "door:2"]
    router.route_update(message(11, -100, "/game", 1), now=NOW)
    router.route_update(press(button(repo, "open_door", actor=11), 11, 2), now=NOW)
    assert repo.get("g").state.phase == "turn.after_door"
    router.route_update(press(button(repo, "loot_room", actor=11), 11, 3), now=NOW)
    assert repo.get("g").state.phase == "turn.charity"
    router.route_update(press(button(repo, "end_turn", actor=11), 11, 4), now=NOW)
    assert repo.get("g").state.active_user_id == 22
    state = repo.games["g"].state
    state.phase = "combat.run_away"
    state.combat = CombatState(fighter_ids=[22], monster_ids=["enemy"], escape_pending={(22, "enemy")})
    router.release.catalog["enemy"] = CardDef("enemy", "door", "monster", "Enemy", bonus=20)
    router.route_update(message(22, 22, "/game", 5), now=NOW)
    roll = button(repo, "run_away", actor=22)
    router.route_update(press(roll, 11, 6), now=NOW)
    assert repo.get("g").state.combat.escape_pending == {(22, "enemy")}
    router.route_update(press(roll, 22, 7), now=NOW)
    assert repo.get("g").state.phase == "turn.charity"
    assert repo.get("g").state.combat is None


def test_play_target_uses_trusted_time_and_curse_never_exposes_foreign_hand():
    repo, router = playing_fixture()
    state = repo.games["g"].state
    state.players[22].level = 3
    router.release.catalog["door:0"] = CardDef("door:0", "door", "curse", "Curse", effects=[{"op": "lose_level", "amount": 1}],
                                             play_phases=("turn.prepare",), target_rule="player")
    router.route_update(message(11, 11, "/hand", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="card:door:0"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "choose_card_target", actor=11), 11, 3), now=NOW)
    target = button(repo, "play_card", actor=11, target={"player_id": 22})
    assert target.args == {"card_id": "door:0", "target": {"player_id": 22}}
    router.route_update(press(target, 11, 4), now=NOW)
    assert repo.get("g").state.players[22].level == 2
    assert "door:0" in repo.get("g").state.door_discard
    foreign_name = router.release.catalog["door:1"].name
    assert not any(foreign_name in str(m["payload"]) for m in repo.outbox if m["payload"].get("chat_id") in {11, -100})


def test_long_private_photo_caption_preserves_complete_rules_in_separate_message():
    from dota_dungeon.telegram.views import View
    repo, router = playing_fixture()
    text = "<b>Rules</b>\n" + "Long rules. " * 200
    messages, _ = router.outgoing_view(repo.get("g"), View("user:11", text, photo="https://example.test/card.png"), NOW)
    assert len(messages[0]["payload"].get("caption", "")) <= 1024
    assert any(m["method"] == "sendMessage" and m["payload"]["text"] == text for m in messages)


def test_persisted_catalog_pin_rejects_actions_against_different_release():
    repo, router = playing_fixture()
    router.route_update(message(11, -100, "/game", 1), now=NOW)
    door = button(repo, "open_door", actor=11)
    repo.games["g"].state.catalog_digest = "b" * 64
    router.route_update(press(door, 11, 2), now=NOW)
    assert repo.get("g").version == 0
    assert repo.get("g").state.phase == "turn.prepare"
