from random import Random
import pytest
from dota_dungeon.core.model import RuleError
from dota_dungeon.core import items, turn, trade
from dota_dungeon.core.play import play_card
from test_card_character import game, NOW, ability


def test_dwarf_has_six_hand_limit_and_unlimited_big_items():
    from dota_dungeon.core.character import effective_hand_limit

    s, c = game(race="dwarf", phase="turn.prepare")
    s.players[1].hand = ["huge_rock", "tuba_of_charm"]
    s, _ = items.carry(s, 1, "huge_rock", c)
    s, _ = items.carry(s, 1, "tuba_of_charm", c)
    assert effective_hand_limit(s, 1, c) == 6
    s.phase = "turn.charity"
    s.players[1].hand = [f"cost{i}" for i in range(6)]
    turn.end_turn(s, 1, catalog=c)


def test_halfling_first_item_each_turn_doubles_sale_and_not_later():
    s, c = game(race="halfling", phase="turn.prepare")
    s.players[1].hand = ["cost0", "cost1", "cost2"]
    s, _ = items.sell(s, 1, ["cost0"], c)
    assert s.players[1].level == 4
    s, _ = items.sell(s, 1, ["cost1", "cost2"], c)
    assert s.players[1].level == 5


def test_positive_value_one_shot_is_carried_sold_and_traded():
    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["magic_missile", "cost0", "cost1"]
    s, _ = items.carry(s, 1, "magic_missile", c)
    with pytest.raises(RuleError):
        items.equip(s, 1, "magic_missile", c)
    from datetime import timedelta

    out, _ = trade.offer_trade(
        s, 1, 2, ["magic_missile"], [], NOW + timedelta(seconds=60), c, NOW
    )
    tid = next(iter(out.trades))
    out, _ = trade.accept_trade(out, 2, tid, c, NOW)
    assert "magic_missile" in out.players[2].in_play
    s.players[1].hand.append("cost2")
    out, _ = items.sell(s, 1, ["magic_missile", "cost0", "cost1"], c)
    assert out.players[1].level == 4


def test_dual_class_and_race_enablers_retain_two_identities():
    s, c = game("warrior", "elf", phase="turn.prepare")
    s.players[1].hand += ["super_munchkin", "thief", "half_breed", "dwarf"]
    for special, identity in [("super_munchkin", "thief"), ("half_breed", "dwarf")]:
        s, _ = play_card(s, 1, special, {}, c, Random(1), NOW)
        s, _ = items.play_identity(s, 1, identity, c)
    assert set(s.players[1].role_ids) == {"warrior", "thief"}
    assert set(s.players[1].race_ids) == {"elf", "dwarf"}


def test_cheat_ignores_restrictions_slots_and_big_capacity_until_item_loss():
    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["shield_of_ubiquity", "cheat", "huge_rock"]
    s, _ = items.carry(s, 1, "shield_of_ubiquity", c)
    s, _ = play_card(
        s,
        1,
        "cheat",
        {"player_id": 1, "card_id": "shield_of_ubiquity"},
        c,
        Random(1),
        NOW,
    )
    s, _ = items.equip(s, 1, "shield_of_ubiquity", c)
    s, _ = items.equip(s, 1, "huge_rock", c)
    from dota_dungeon.core.effects import apply_effects

    s, _ = apply_effects(
        s, 1, [{"op": "remove_item", "card_id": "shield_of_ubiquity"}], c
    )
    assert "cheat" in s.door_discard
    assert "cheat" not in s.players[1].in_play


def test_hireling_carries_item_and_loss_discards_both():
    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["hireling", "shield_of_ubiquity"]
    s, _ = play_card(s, 1, "hireling", {}, c, Random(1), NOW)
    s, _ = items.assign_hireling(s, 1, "hireling", "shield_of_ubiquity", c)
    assert "shield_of_ubiquity" in s.players[1].in_play
    from dota_dungeon.core.effects import apply_effects

    s, _ = apply_effects(s, 1, [{"op": "remove_item", "card_id": "hireling"}], c)
    assert set(s.treasure_discard) == {"hireling", "shield_of_ubiquity"}
    assert not s.players[1].in_play


def test_identity_loss_deactivates_restricted_equipment():
    s, c = game("warrior", phase="turn.prepare")
    s.players[1].hand = ["shield_of_ubiquity"]
    s, _ = items.equip(s, 1, "shield_of_ubiquity", c)
    from dota_dungeon.core.effects import apply_effects

    s, _ = apply_effects(s, 1, [{"op": "remove_item", "card_id": "warrior"}], c)
    assert not s.players[1].equipped
    assert "shield_of_ubiquity" in s.players[1].in_play


def test_single_half_breed_ignores_race_disadvantage():
    s, c = game(race="elf", phase="turn.prepare")
    s.players[1].hand.append("half_breed")
    s, _ = play_card(s, 1, "half_breed", {}, c, Random(1), NOW)
    s.phase = "combat.active"
    from dota_dungeon.core.model import CombatState

    s.combat = CombatState(fighter_ids=[1], monster_ids=["squidzilla"])
    from dota_dungeon.core.combat import combat_totals

    assert combat_totals(s, c)[1] == 18


def test_carried_rat_escape_does_not_require_equipping():
    s, c = game(phase="combat.run_away")
    s.players[1].in_play = ["rat_on_a_stick"]
    s.combat.escape_pending = {(1, "monster")}
    s, _ = ability(
        s, c, "rat_on_a_stick_escape", ["rat_on_a_stick"], {"monster_id": "monster"}
    )
    assert s.combat is None
    assert "rat_on_a_stick" in s.treasure_discard


def test_dwarf_loss_keeps_refs_until_explicit_excess_choice():
    s, c = game(race="dwarf", phase="turn.prepare")
    s.players[1].hand = ["huge_rock", "tuba_of_charm"]
    s, _ = items.equip(s, 1, "huge_rock", c)
    s, _ = items.carry(s, 1, "tuba_of_charm", c)
    s, _ = items.discard_identity(s, 1, "dwarf", c)
    assert s.players[1].pending_big_excess == 1
    assert s.players[1].equipped == ["huge_rock"]
    s.players[2].in_play = ["mithril_armor"]
    s.players[3].in_play = ["swiss_army_polearm"]
    s, _ = items.resolve_big_items(s, 1, ["tuba_of_charm"], c)
    assert s.players[1].pending_big_excess == 0
    assert s.players[1].equipped == ["huge_rock"]


def test_loss_of_dual_enabler_requires_identity_choice():
    s, c = game("warrior", phase="turn.prepare")
    s.players[1].hand += ["super_munchkin", "thief"]
    s, _ = play_card(s, 1, "super_munchkin", {}, c, Random(1), NOW)
    s, _ = items.play_identity(s, 1, "thief", c)
    s, _ = items.discard_identity(s, 1, "super_munchkin", c)
    assert set(s.players[1].role_ids) == {"warrior", "thief"}
    assert s.players[1].pending_identity_excess == {"role": 1}
    s, _ = items.resolve_identity_excess(s, 1, ["warrior"], c)
    assert s.players[1].role_ids == ["thief"]
    assert not s.players[1].pending_identity_excess


def test_last_race_loss_discards_halfbreed_and_sex_restrictions_are_game_trait():
    s, c = game(race="elf", phase="turn.prepare")
    s.players[1].hand.append("half_breed")
    s, _ = play_card(s, 1, "half_breed", {}, c, Random(1), NOW)
    s, _ = items.discard_identity(s, 1, "elf", c)
    assert "half_breed" in s.door_discard
    s.players[1].character_sex = "male"
    assert not items.can_use(s.players[1], "broad_sword", c)
    s.players[1].character_sex = "female"
    assert items.can_use(s.players[1], "broad_sword", c)


def test_hireling_escape_discards_assigned_item_and_cannot_discard_other_item_as_cost():
    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["hireling", "shield_of_ubiquity"]
    s, _ = play_card(s, 1, "hireling", {}, c, Random(1), NOW)
    s, _ = items.assign_hireling(s, 1, "hireling", "shield_of_ubiquity", c)
    from dota_dungeon.core.model import CombatState

    s.phase = "combat.run_away"
    s.combat = CombatState(
        fighter_ids=[1], monster_ids=["monster"], escape_pending={(1, "monster")}
    )
    with pytest.raises(RuleError):
        ability(
            s, c, "hireling_escape", ["shield_of_ubiquity"], {"monster_id": "monster"}
        )
    out, _ = ability(s, c, "hireling_escape", ["hireling"], {"monster_id": "monster"})
    assert out.combat is None
    assert set(out.treasure_discard) == {"hireling", "shield_of_ubiquity"}


def test_default_human_qualifies_but_single_halfbreed_does_not_for_human_items():
    s, c = game(phase="turn.prepare")
    assert items.can_use(s.players[1], "bad_ass_bandana", c)
    s, c = game(race="elf", phase="turn.prepare")
    assert not items.can_use(s.players[1], "bad_ass_bandana", c)
    s.players[1].hand.append("half_breed")
    s, _ = play_card(s, 1, "half_breed", {}, c, Random(1), NOW)
    assert not items.can_use(s.players[1], "bad_ass_bandana", c)


def test_single_super_munchkin_ignores_class_penalties():
    s, c = game("wizard", phase="turn.prepare")
    assert not items.can_use(s.players[1], "mithril_armor", c)
    s.players[1].hand.append("super_munchkin")
    s, _ = play_card(s, 1, "super_munchkin", {}, c, Random(1), NOW)
    assert items.can_use(s.players[1], "mithril_armor", c)


def test_items_can_be_carried_and_equipped_on_other_noncombat_turn():
    from dota_dungeon.core.engine import decide
    from dota_dungeon.core.model import Command

    s, c = game(phase="turn.after_door")
    s.active_user_id = 2
    s.turn_number = 4
    s.players[1].hand = ["huge_rock"]
    s, _ = decide(
        s,
        Command("g", 1, "carry", "carry_item", {"card_id": "huge_rock"}),
        c,
        Random(2),
    )
    s, _ = decide(
        s, Command("g", 1, "equip", "equip", {"card_id": "huge_rock"}), c, Random(2)
    )
    assert s.players[1].equipped == ["huge_rock"]


def test_really_impressive_title_stays_in_play_gives_permanent_bonus_without_item_status():
    from dota_dungeon.core.combat import combat_strength

    s, c = game(phase="turn.prepare")
    s.players[1].hand.append("really_impressive_title")
    s, _ = play_card(s, 1, "really_impressive_title", {}, c, Random(1), NOW)
    assert "really_impressive_title" in s.players[1].in_play
    assert combat_strength(s, 1, c) == 6
    with pytest.raises(RuleError):
        items.sell(s, 1, ["really_impressive_title"], c)


def test_no_value_pretty_balloons_is_carried_item_and_item_loss_target():
    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["pretty_balloons"]
    s, _ = items.carry(s, 1, "pretty_balloons", c)
    from dota_dungeon.core.effects import apply_effects

    s, _ = apply_effects(
        s,
        1,
        [{"op": "remove_item", "selector": {"kind": "item", "zone": "in_play"}}],
        c,
    )
    assert not s.players[1].in_play
    assert "pretty_balloons" in s.treasure_discard


def test_cheat_can_atomically_carry_second_big_item_from_own_hand():
    s, c = game(phase="turn.prepare")
    s.players[1].in_play = ["huge_rock"]
    s.players[1].hand = ["shield_of_ubiquity", "cheat"]
    s, _ = play_card(
        s,
        1,
        "cheat",
        {"player_id": 1, "card_id": "shield_of_ubiquity"},
        c,
        Random(1),
        NOW,
    )
    assert set(s.players[1].in_play) == {"huge_rock", "shield_of_ubiquity", "cheat"}
    assert not s.players[1].hand
    s, _ = items.equip(s, 1, "shield_of_ubiquity", c)
    assert s.players[1].pending_big_excess == 0


def test_cheat_wrong_kind_another_hand_and_self_target_reject_atomically():
    from copy import deepcopy

    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["cheat", "warrior"]
    s.players[2].hand = ["shield_of_ubiquity"]
    r = Random(2)
    before = deepcopy(s)
    rngbefore = r.getstate()
    for target in [
        {"player_id": 1, "card_id": "cheat"},
        {"player_id": 1, "card_id": "warrior"},
        {"player_id": 2, "card_id": "shield_of_ubiquity"},
    ]:
        with pytest.raises(RuleError):
            play_card(s, 1, "cheat", target, c, r, NOW)
    assert s == before
    assert r.getstate() == rngbefore


def test_mandatory_excess_blocks_declare_result_and_commands_without_losing_refs():
    from dota_dungeon.core.engine import decide
    from dota_dungeon.core.model import Command
    from dota_dungeon.core.combat import declare_result

    s, c = game()
    s.players[1].pending_identity_excess = {"role": 1}
    with pytest.raises(RuleError, match="excess"):
        declare_result(s, 1, c)
    with pytest.raises(RuleError, match="excess"):
        decide(s, Command("g", 1, "roll", "begin_escape"), c, Random(1))


def test_excess_big_item_choice_rejects_wrong_recipient_and_transfers_to_lowest_eligible():
    s, c = game(race="dwarf", phase="turn.prepare")
    s.players[1].hand = ["huge_rock", "tuba_of_charm"]
    s, _ = items.carry(s, 1, "huge_rock", c)
    s, _ = items.carry(s, 1, "tuba_of_charm", c)
    s, _ = items.discard_identity(s, 1, "dwarf", c)
    s.players[2].level = 1
    s.players[3].level = 2
    with pytest.raises(RuleError):
        items.resolve_big_items(s, 1, ["tuba_of_charm"], c, 3)
    out, _ = items.resolve_big_items(s, 1, ["tuba_of_charm"], c, 2)
    assert out.players[2].in_play == ["tuba_of_charm"]
    assert out.players[1].in_play == ["huge_rock"]


def test_all_printed_one_shot_items_use_shared_classifier():
    s, c = game()
    shots = [card for card in c.values() if card.kind == "one_shot"]
    assert len(shots) == 22
    assert all(items.is_item_card(card) for card in shots)


def test_excess_big_items_cannot_discard_while_lowest_player_can_carry_and_dwarf_recipient_unlimited():
    s, c = game(race="dwarf", phase="turn.prepare")
    s.players[1].hand = ["huge_rock", "tuba_of_charm", "mithril_armor"]
    for cid in s.players[1].hand.copy():
        s, _ = items.carry(s, 1, cid, c)
    s, _ = items.discard_identity(s, 1, "dwarf", c)
    with pytest.raises(RuleError):
        items.resolve_big_items(s, 1, ["tuba_of_charm", "mithril_armor"], c)
    s.players[2].race_ids = ["dwarf"]
    s.players[2].in_play = ["dwarf"]
    s.players[2].level = 1
    s, _ = items.resolve_big_items(s, 1, ["tuba_of_charm", "mithril_armor"], c, 2)
    assert s.players[1].pending_big_excess == 0
    assert set(s.players[2].in_play) == {"dwarf", "tuba_of_charm", "mithril_armor"}


def test_excess_big_items_can_be_sold_on_own_turn_with_other_items():
    from dota_dungeon.core.engine import decide
    from dota_dungeon.core.model import Command

    s, c = game(race="dwarf", phase="turn.prepare")
    s.players[1].hand = ["huge_rock", "tuba_of_charm", "cost0", "cost1"]
    s, _ = items.carry(s, 1, "huge_rock", c)
    s, _ = items.carry(s, 1, "tuba_of_charm", c)
    s, _ = items.discard_identity(s, 1, "dwarf", c)
    out, _ = decide(
        s,
        Command(
            "g", 1, "sale", "sell", {"card_ids": ["tuba_of_charm", "cost0", "cost1"]}
        ),
        c,
        Random(1),
    )
    assert out.players[1].pending_big_excess == 0
    assert out.players[1].level == 4
    s.active_user_id = 2
    with pytest.raises(RuleError):
        decide(
            s,
            Command(
                "g",
                1,
                "sale-other",
                "sell",
                {"card_ids": ["tuba_of_charm", "cost0", "cost1"]},
            ),
            c,
            Random(1),
        )


def test_help_item_transfer_reconciles_cheat_attachment_loss():
    from dota_dungeon.core.combat import resolve_rewards

    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["shield_of_ubiquity", "cheat"]
    s, _ = items.carry(s, 1, "shield_of_ubiquity", c)
    s, _ = play_card(
        s, 1, "cheat", {"card_id": "shield_of_ubiquity"}, c, Random(1), NOW
    )
    from dota_dungeon.core.model import CombatState

    s.phase = "combat.active"
    s.combat = CombatState(
        fighter_ids=[1, 2],
        helper_id=2,
        monster_ids=["monster"],
        help_item_ids=["shield_of_ubiquity"],
    )
    out, _ = resolve_rewards(s, c, Random(1))
    assert "cheat" in out.door_discard
    assert out.players[1].attachments == {}
    assert "shield_of_ubiquity" in out.players[2].in_play


def test_hireling_swaps_assigned_item_preserving_old_carried_item_and_capacity():
    s, c = game(phase="turn.prepare")
    s.players[1].hand = ["hireling", "shield_of_ubiquity", "huge_rock", "tuba_of_charm"]
    s, _ = play_card(s, 1, "hireling", {}, c, Random(2), NOW)
    s, _ = items.assign_hireling(s, 1, "hireling", "shield_of_ubiquity", c)
    s, _ = items.carry(s, 1, "tuba_of_charm", c)
    out, _ = items.assign_hireling(s, 1, "hireling", "huge_rock", c)
    assert out.players[1].hireling_items == {"hireling": "huge_rock"}
    assert "shield_of_ubiquity" in out.players[1].in_play
    assert "shield_of_ubiquity" not in out.players[1].equipped
    assert out.players[1].pending_big_excess == 1
    assert not out.treasure_discard
