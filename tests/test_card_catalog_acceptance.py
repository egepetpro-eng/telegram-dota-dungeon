"""Real shipped cards exercise the public command boundary and physical zones."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from random import Random

import pytest

from dota_dungeon.cards.installed import load_installed_media, validate_installed_release
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command, RuleError
from dota_dungeon.core.setup import new_lobby

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def release():
    return validate_installed_release()


def one_zone(state, catalog):
    ids = state.door_deck + state.treasure_deck + state.door_discard + state.treasure_discard
    for player in state.players.values():
        ids += player.hand + player.in_play
    for corpse in state.corpse.values():
        ids += corpse
    ids += getattr(state, "resolving_card_ids", [])
    if state.combat:
        ids += [cid for cid in state.combat.monster_ids if cid in catalog]
        ids += state.combat.played_card_ids + state.combat.charmed_monster_ids
        ids += getattr(state.combat, "retired_monster_ids", [])
    assert Counter(ids) == Counter(catalog.keys())


def apply(state, release, rng, actor, action, **args):
    result, events = decide(state, Command(state.game_id, actor, str(len(state.processed_requests)) + action,
                           action, args), release.catalog, rng)
    one_zone(result, release.catalog)
    return result, events


def lobby(release, count):
    state = new_lobby("acceptance", -100, 1, release.catalog)
    state.catalog_version, state.catalog_digest = release.version, release.digest
    rng = Random(37)
    for uid in range(1, count + 1):
        state, _ = apply(state, release, rng, uid, "join")
        state, _ = apply(state, release, rng, uid, "ready", ready=True)
    return state, rng


def prepared(release):
    state, rng = lobby(release, 2)
    # Controlled legal fixture: every card remains in its own pile until assigned.
    state.phase, state.active_user_id, state.turn_number = "turn.prepare", 1, 1
    return state, rng


def hand(state, card_id, user_id):
    pile = state.door_deck if state.card_decks[card_id] == "door" else state.treasure_deck
    pile.remove(card_id)
    state.players[user_id].hand.append(card_id)


def top_door(state, card_id):
    state.door_deck.remove(card_id)
    state.door_deck.append(card_id)


def test_installed_release_and_artwork_cover_every_physical_card(release):
    assert len(release.catalog) == 168
    assert Counter(card.deck for card in release.catalog.values()) == {"door": 95, "treasure": 73}
    assert len({card.rule_key for card in release.catalog.values()}) == 147
    media = load_installed_media(release)
    assert all(media.image_for(cid) for cid in release.catalog)
    assert all(p.description_ru.strip() and p.dota_entity_id and p.source_refs for p in release.presentations.values())


@pytest.mark.parametrize("count", [2, 6])
def test_real_catalog_initial_deal_preserves_all_cards_and_hidden_audiences(release, count):
    state, rng = lobby(release, count)
    state, events = apply(state, release, rng, 1, "start")
    assert state.phase == "turn.prepare"
    assert all(len(player.hand) >= 8 for player in state.players.values())
    for event in events:
        if event.name == "card.drawn":
            assert event.audience == f"user:{event.data['recipient_id']}"
    assert state.catalog_digest == release.digest


def test_real_one_shot_items_sell_carry_trade_and_gual_can_target_another_player(release):
    state, rng = prepared(release)
    hand(state, "wand_of_dowsing:1", 1)
    state, _ = apply(state, release, rng, 1, "sell", card_ids=["wand_of_dowsing:1"])
    assert state.players[1].level == 2  # Printed 1100 gold, no change wallet.
    hand(state, "magic_missile:1", 1)
    hand(state, "wishing_ring:1", 2)
    state, _ = apply(state, release, rng, 1, "carry_item", card_id="magic_missile:1")
    state, _ = apply(state, release, rng, 2, "carry_item", card_id="wishing_ring:1")
    state, events = apply(state, release, rng, 1, "offer_trade", partner_id=2,
                         offered_ids=["magic_missile:1"], requested_ids=["wishing_ring:1"],
                         now=NOW, expires_at=NOW + timedelta(seconds=120))
    trade_id = events[0].data["trade_id"]
    state, _ = apply(state, release, rng, 2, "accept_trade", trade_id=trade_id, now=NOW)
    assert "magic_missile:1" in state.players[2].in_play
    assert "wishing_ring:1" in state.players[1].in_play
    assert not state.players[1].equipped and not state.players[2].equipped
    hand(state, "boil_an_anthill:1", 1)
    state, _ = apply(state, release, rng, 1, "play_card", card_id="boil_an_anthill:1", target={"player_id": 2}, now=NOW)
    assert state.players[2].level == 2


def test_real_turn_loot_charity_and_end_turn_preserve_inventory(release):
    state, rng = prepared(release)
    state.players[1].level = 3
    for key in ("warrior", "thief", "cleric", "wizard", "dwarf", "halfling"):
        hand(state, key + ":1", 1)
    top_door(state, "elf:2")
    state, _ = apply(state, release, rng, 1, "open_door")
    top_door(state, "elf:3")
    state, events = apply(state, release, rng, 1, "loot_room")
    assert len(state.players[1].hand) == 8
    assert all(event.audience == "user:1" for event in events if event.name == "card.drawn")
    given = state.players[1].hand[:3]
    state, _ = apply(state, release, rng, 1, "give_charity", assignments={2: given})
    assert len(state.players[1].hand) == 5
    assert state.players[2].hand == given
    state, _ = apply(state, release, rng, 1, "end_turn")
    assert state.active_user_id == 2


def test_real_equipment_normal_combat_and_legal_winning_level(release):
    state, rng = prepared(release)
    state.players[1].level = 9
    hand(state, "chainsaw_of_bloody_dismemberment:1", 1)
    state, _ = apply(state, release, rng, 1, "equip", card_id="chainsaw_of_bloody_dismemberment:1")
    top_door(state, "net_troll:1")
    state, _ = apply(state, release, rng, 1, "open_door")
    state, _ = apply(state, release, rng, 1, "declare_win", now=NOW)
    state, _ = apply(state, release, rng, 2, "pass_reaction")
    state, events = apply(state, release, rng, 1, "close_reaction", now=NOW)
    assert state.phase == "game.finished"
    assert state.players[1].level == 10
    assert any(event.name == "game.won" for event in events)
    assert all(event.audience == "user:1" for event in events if event.name == "treasure.drawn")


def test_real_item_sale_cannot_grant_winning_level(release):
    state, rng = prepared(release)
    state.players[1].level = 9
    hand(state, "wand_of_dowsing:1", 1)
    with pytest.raises(RuleError):
        apply(state, release, rng, 1, "sell", card_ids=["wand_of_dowsing:1"])
    assert state.players[1].hand == ["wand_of_dowsing:1"]
