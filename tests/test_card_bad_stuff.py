from copy import deepcopy
from datetime import timedelta
from random import Random
import pytest
from tests.test_card_character import game, NOW
from tests.test_card_combat import command, play
from dota_dungeon.core.model import RuleError
from dota_dungeon.core import combat, card_rules


def respond(s, c, choices=None, actor=1):
    return command(
        s,
        c,
        "respond_decision",
        actor,
        decision_id=s.pending_decision.id,
        choices=choices or {},
    )


def test_ring_cancels_before_level_loss_and_consumes_each_card_once():
    s, c = game(phase="turn.prepare", level=5)
    s, _ = play(s, c, "curse_lose_a_level", {"player_id": 1}, actor=2)
    assert s.players[1].level == 5 and s.pending_decision.kind == "curse_response"
    s, _ = play(
        s,
        c,
        "wishing_ring",
        {"player_id": 1},
        {"effect_id": s.pending_decision.id},
        actor=3,
    )
    assert s.players[1].level == 5 and s.pending_decision is None
    assert (
        s.door_discard.count("curse_lose_a_level") == 1
        and s.treasure_discard.count("wishing_ring") == 1
    )


def test_victim_selects_small_item_privately_and_mandatory_expiry_rejects():
    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["pretty_balloons", "cost0"]
    s, _ = play(s, c, "curse_lose_a_small_item", {"player_id": 1}, actor=2)
    s, _ = respond(s, c)
    assert s.pending_decision.kind == "loss_choice"
    assert set(card_rules.decision_options(s, 1, c)["choices"]["card_ids"]) == {
        "pretty_balloons",
        "cost0",
    }
    assert card_rules.decision_options(s, 2, c)["choices"] == {}
    before = deepcopy(s)
    with pytest.raises(RuleError):
        command(
            s,
            c,
            "expire_decision",
            decision_id=s.pending_decision.id,
            now=NOW + timedelta(days=1),
        )
    with pytest.raises(RuleError):
        respond(s, c, {"card_ids": ["cost0"]}, 2)
    assert s == before
    s, _ = respond(s, c, {"card_ids": ["pretty_balloons"]})
    assert s.players[1].hand == ["cost0"] and s.pending_decision is None


def test_snails_stored_die_and_victim_selects_union_not_entire_hand():
    s, c = game(level=8)
    s.combat.monster_ids = ["snails_on_speed"]
    s, _ = combat.apply_bad_stuff(s, 1, "snails_on_speed", c, rng=Random(1), now=NOW)
    assert s.pending_decision.kind == "die_response"
    s, _ = play(
        s, c, "loaded_die", choices={"roll_id": s.pending_decision.id, "result": 2}
    )
    s, _ = respond(s, c)
    assert s.pending_decision.kind == "loss_choice"
    s, _ = respond(s, c, {"card_ids": ["cost0", "cost1"]})
    assert s.players[1].hand == ["cost2", "cost3", "cost4", "cost5"]


def test_orcs_die_is_independent_and_loaded_die_precedes_death():
    s, c = game(level=8)
    s.combat.monster_ids = ["3_872_orcs"]
    s, _ = combat.apply_bad_stuff(s, 1, "3_872_orcs", c, rng=Random(1), now=NOW)
    assert s.players[1].alive
    s, _ = play(
        s, c, "loaded_die", choices={"roll_id": s.pending_decision.id, "result": 6}
    )
    s, _ = respond(s, c)
    assert s.players[1].alive and s.players[1].level == 2


def test_crabs_body_mapping_uses_worn_below_waist_and_all_open_armor():
    s, c = game()
    s.combat.monster_ids = ["crabs"]
    s.players[1].in_play = [
        "leather_armor",
        "slimy_armor",
        "pantyhose_of_giant_strength",
        "spiky_knees",
        "kneepads_of_allure",
        "boots_of_butt_kicking",
        "sandals_of_protection",
        "stepladder",
    ]
    s.players[1].equipped = [
        "leather_armor",
        "pantyhose_of_giant_strength",
        "spiky_knees",
        "kneepads_of_allure",
        "boots_of_butt_kicking",
    ]
    s, _ = combat.apply_bad_stuff(s, 1, "crabs", c, rng=Random(1), now=NOW)
    assert set(s.players[1].in_play) == {"sandals_of_protection", "stepladder"}


@pytest.mark.parametrize(
    "key,expected",
    [
        ("wight_brothers", 1),
        ("ghoulfiends", 3),
        ("tongue_demon", 6),
        ("amazon", 5),
    ],
)
def test_printed_bad_stuff_level_variants(key, expected):
    s, c = game(level=8)
    s.combat.monster_ids = [key]
    s, _ = combat.apply_bad_stuff(s, 1, key, c, rng=Random(1), now=NOW)
    assert s.players[1].level == expected


@pytest.mark.parametrize(
    "key",
    [
        "bullrog",
        "plutonium_dragon",
        "squidzilla",
        "stoned_golem",
        "unspeakably_awful_indescribable_horror",
    ],
)
def test_death_keeps_identities_levels_and_exposes_corpse(key):
    s, c = game(role="wizard", race="elf", level=8)
    s.combat.monster_ids = [key]
    if key == "unspeakably_awful_indescribable_horror":
        s.players[1].role_ids = []
        s.players[1].in_play.remove("wizard")
    s, _ = combat.apply_bad_stuff(s, 1, key, c, rng=Random(1), now=NOW)
    assert not s.players[1].alive and s.players[1].level == 8
    assert s.players[1].race_ids == ["elf"] and len(s.corpse[1]) == 6
    assert not s.players[1].hand


def test_income_tax_victim_then_other_payers_choose_value():
    s, c = game(phase="turn.prepare")
    s.players[2].hand = ["cost6", "cost7"]
    s.treasure_deck = []
    s, _ = play(s, c, "curse_income_tax", {"player_id": 1}, actor=3)
    s, _ = respond(s, c)
    s, _ = respond(s, c, {"card_ids": ["cost0"]})
    assert s.pending_decision.chooser_ids == [2]
    s, _ = respond(s, c, {"card_ids": ["cost6"]}, 2)
    assert s.players[3].level == 2 and s.pending_decision is None


def test_net_troll_party_maximum_receiver_controls_open_item():
    s, c = game(level=3)
    s.combat.monster_ids = ["net_troll"]
    s.players[2].level = 7
    s.players[3].level = 6
    s.players[1].hand.remove("cost0")
    s.players[1].in_play = ["cost0"]
    s, _ = combat.apply_bad_stuff(s, 1, "net_troll", c, rng=Random(1), now=NOW)
    assert s.pending_decision.chooser_ids == [2]
    assert card_rules.decision_options(s, 2, c)["choices"]["card_ids"] == ["cost0"]
    s, _ = respond(s, c, {"card_ids": ["cost0"]}, 2)
    assert "cost0" in s.players[2].in_play and "cost0" not in s.players[1].in_play


def test_hippogriff_receiver_can_choose_blind_hand_despite_open_treasure():
    s, c = game()
    s.combat.monster_ids = ["hippogriff"]
    s.players[1].hand = ["cost0"]
    s.players[1].in_play = ["cost1"]
    s, _ = combat.apply_bad_stuff(s, 1, "hippogriff", c, rng=Random(1), now=NOW)
    assert s.pending_decision.chooser_ids == [3]
    s, _ = respond(s, c, {"option": "blind"}, 3)
    assert "cost0" in s.players[3].hand and s.pending_decision.chooser_ids == [2]
    s, _ = respond(s, c, {"option": "cost1"}, 2)
    assert "cost1" in s.players[2].in_play and not s.players[1].in_play


def test_chicken_is_removed_even_when_headgear_loss_finds_no_helmet():
    s, c = game()
    s.combat.monster_ids = ["bigfoot"]
    s.players[1].in_play = ["curse_chicken_on_your_head"]
    s, _ = combat.apply_bad_stuff(s, 1, "bigfoot", c, rng=Random(1), now=NOW)
    assert s.players[1].in_play == [] and s.door_discard == [
        "curse_chicken_on_your_head"
    ]


def test_kill_hireling_level_goes_to_actor_not_owner():
    s, c = game(phase="turn.prepare")
    s.players[2].in_play = ["hireling"]
    s.players[1].hand += ["kill_the_hireling"]
    s, _ = play(s, c, "kill_the_hireling", {"player_id": 2, "card_id": "hireling"})
    assert s.players[1].level == 4 and s.players[2].level == 3


def test_whine_checks_beneficiary_rank():
    s, c = game(phase="turn.prepare")
    s.players[2].level = 6
    s.players[1].hand += ["whine_at_the_gm"]
    with pytest.raises(RuleError):
        play(s, c, "whine_at_the_gm", {"player_id": 2})


def test_nonpursued_wight_does_not_cost_escape_levels():
    s, c = game(level=3)
    s.combat.monster_ids = ["wight_brothers"]
    s, _ = combat.begin_escape(s, 1, c)
    assert s.players[1].level == 3


def test_leperchaun_neighbors_take_instead_of_discard():
    s, c = game(level=7)
    s.combat.monster_ids = ["leperchaun"]
    s.players[1].in_play = ["pretty_balloons", "magic_missile"]
    s, _ = combat.apply_bad_stuff(s, 1, "leperchaun", c, rng=Random(1), now=NOW)
    s, _ = respond(s, c, {"card_ids": ["pretty_balloons"]}, 2)
    s, _ = respond(s, c, {"card_ids": ["magic_missile"]}, 3)
    assert (
        "pretty_balloons" in s.players[2].in_play
        and "magic_missile" in s.players[3].in_play
    )


def test_hippogriff_repeats_circuit_until_all_treasures_taken():
    s, c = game()
    s.combat.monster_ids = ["hippogriff"]
    s.players[1].hand = []
    s.players[1].in_play = ["cost0", "cost1", "cost2"]
    s, _ = combat.apply_bad_stuff(s, 1, "hippogriff", c, rng=Random(1), now=NOW)
    for uid, cid in [(3, "cost0"), (2, "cost1"), (3, "cost2")]:
        s, _ = respond(s, c, {"option": cid}, uid)
    assert not s.players[1].in_play and s.pending_decision is None


def test_dead_player_cannot_receive_draw_trade_or_loot():
    from dota_dungeon.core.draw import draw_cards
    from dota_dungeon.core.trade import offer_trade

    s, c = game(phase="turn.prepare")
    s.players[2].alive = False
    with pytest.raises(RuleError):
        draw_cards(s, 2, "treasure", 1, False, c, Random(1))
    s.players[1].in_play = ["pretty_balloons"]
    with pytest.raises(RuleError):
        offer_trade(
            s, 1, 2, ["pretty_balloons"], [], NOW + timedelta(seconds=30), c, NOW
        )
    s.corpse[3] = ["cost0"]
    s.corpse_looted_by[3] = set()
    with pytest.raises(RuleError):
        combat.loot_corpse(s, 2, 3, "cost0")


def test_corpse_is_public_and_highest_level_living_player_loots_first():
    s, c = game()
    s.combat.monster_ids = ["bullrog"]
    s.players[2].level = 6
    s.players[3].level = 4
    s, events = combat.apply_bad_stuff(s, 1, "bullrog", c, rng=Random(1), now=NOW)
    assert (
        next(e for e in events if e.name == "player.died").data["card_ids"]
        == s.corpse[1]
    )
    with pytest.raises(RuleError):
        combat.loot_corpse(s, 3, 1, "cost0")
    s, _ = combat.loot_corpse(s, 2, 1, "cost0")
    s, _ = combat.loot_corpse(s, 3, 1, "cost1")
    assert not s.corpse[1] and set(s.treasure_discard) >= {
        "cost2",
        "cost3",
        "cost4",
        "cost5",
    }
