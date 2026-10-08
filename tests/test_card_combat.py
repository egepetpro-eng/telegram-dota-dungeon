from copy import deepcopy
from datetime import timedelta
from random import Random
import pytest
from tests.test_card_character import game, NOW
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command, RuleError
from dota_dungeon.core import combat


def command(s, c, name, actor=1, **args):
    return decide(
        s,
        Command(
            "g",
            actor,
            str(len(s.processed_requests)) + name,
            name,
            {"now": NOW, **args},
        ),
        c,
        Random(11),
    )


def play(s, c, key, target=None, choices=None, actor=1):
    if key not in s.players[actor].hand:
        s.players[actor].hand.append(key)
    return command(
        s,
        c,
        "play_card",
        actor,
        card_id=key,
        target=target or {},
        choices=choices or {},
    )


def test_mate_copies_enhancers_in_both_orders_and_has_no_physical_duplicate():
    for first in ("ancient", "mate"):
        s, c = game(level=9)
        s.combat.monster_ids = ["lame_goblin"]
        s, _ = play(s, c, first, {"monster_id": "lame_goblin"})
        s, _ = play(
            s,
            c,
            "mate" if first == "ancient" else "ancient",
            {"monster_id": "lame_goblin"},
        )
        assert combat.combat_totals(s, c) == (9, 22)
        assert len(s.combat.monster_ids) == 2
        assert (
            sum(combat.monster_rewards(s, m, c)[1] for m in s.combat.monster_ids) == 6
        )
        assert len(s.combat.virtual_monsters) == 1
        assert s.combat.played_card_ids.count("mate") == 1


def test_wandering_monster_consumes_both_sources_atomically():
    s, c = game()
    s.players[2].hand = ["wandering_monster", "gazebo"]
    s.combat.helper_id = 3
    s.combat.fighter_ids = [1, 3]
    old = deepcopy(s)
    rng = Random(17)
    before = rng.getstate()
    with pytest.raises(RuleError):
        decide(
            s,
            Command(
                "g",
                2,
                "invalid",
                "play_card",
                {
                    "card_id": "wandering_monster",
                    "target": {},
                    "choices": {"monster_card_id": "cost0"},
                    "now": NOW,
                },
            ),
            c,
            rng,
        )
    assert s == old and rng.getstate() == before
    s, _ = play(
        s, c, "wandering_monster", choices={"monster_card_id": "gazebo"}, actor=2
    )
    assert s.combat.monster_ids == ["monster", "gazebo"]
    assert s.combat.fighter_ids == [1] and s.combat.helper_id is None
    assert s.players[2].hand == []


def test_undead_join_without_wandering_card():
    s, c = game()
    s.combat.monster_ids = ["mr_bones"]
    s.players[2].hand = ["undead_horse"]
    s, _ = command(s, c, "join_undead", 2, card_id="undead_horse")
    assert combat.combat_totals(s, c) == (3, 6)


def test_last_foe_polymorph_settles_and_discards_source_once():
    s, c = game()
    s.combat.monster_ids = ["lame_goblin"]
    s, _ = play(s, c, "pollymorph_potion", {"monster_id": "lame_goblin"})
    assert s.combat is None and s.players[1].level == 3
    assert len(s.players[1].hand) == 7
    assert s.treasure_discard.count("pollymorph_potion") == 1
    assert s.door_discard.count("lame_goblin") == 1


def test_doppleganger_doubles_later_fighter_boost():
    s, c = game(level=7)
    s, _ = play(s, c, "doppleganger")
    s, _ = play(s, c, "pretty_balloons", choices={"side": "fighters"})
    assert combat.combat_totals(s, c)[0] == 24


def test_reaction_duration_preserved_after_intervention():
    s, c = game(level=9)
    s, _ = combat.declare_win(s, 1, c, NOW, seconds=71)
    s, _ = play(s, c, "pretty_balloons", choices={"side": "fighters"})
    assert s.combat.reaction_deadline == NOW + timedelta(seconds=71)


@pytest.mark.parametrize(
    "foe,level,strength,expected",
    [("ghoulfiends", 4, 8, 4), ("insurance_salesman", 4, 8, 8)],
)
def test_printed_fighter_strength_restrictions(foe, level, strength, expected):
    s, c = game(level=level)
    s.players[1].strength_bonus = strength
    s.combat.monster_ids = [foe]
    assert combat.combat_totals(s, c)[0] == expected


def test_force_help_requires_kneepads_and_no_winning_level():
    s, c = game(level=4)
    s.players[2].level = 5
    s.players[1].in_play = ["kneepads_of_allure"]
    s.players[1].equipped = ["kneepads_of_allure"]
    s, _ = command(s, c, "force_help", helper_id=2)
    assert s.combat.helper_id == 2


def test_transfer_keeps_turn_owner_and_earned_original_rewards():
    s, c = game(level=4)
    s.combat.monster_ids = ["floating_nose", "lame_goblin"]
    s, _ = play(s, c, "potion_of_halitosis", {"monster_id": "floating_nose"})
    assert s.players[1].level == 4
    s, _ = play(s, c, "transferral_potion", {"player_id": 2})
    assert s.active_user_id == 1 and s.combat.leader_id == 2
    s, _ = combat.resolve_rewards(s, c, Random(1))
    assert s.players[1].level == 5 and s.players[2].level == 4 and s.combat is None
    assert s.phase == "turn.after_door"


def test_cleric_choices_wait_for_both_reward_recipients():
    s, c = game(role="cleric", level=4)
    s.players[2].role_ids = ["cleric2"]
    s.players[2].in_play = ["cleric2"]
    s.players[2].hand = ["cost6"]
    s.treasure_deck = ["cost7"]
    from dataclasses import replace

    c["cleric2"] = replace(c["cleric"], id="cleric2")
    s.card_decks["cleric2"] = "door"
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    s.combat.help_treasure_count = 1
    s.treasure_discard = ["pretty_balloons", "magic_lamp"]
    s, _ = combat.declare_win(s, 1, c, NOW)
    s, _ = combat.close_reaction(s, c, NOW + timedelta(seconds=30), Random(1))
    assert s.pending_decision.kind == "reward_draw" and set(
        s.pending_decision.chooser_ids
    ) == {1, 2}
    s, _ = command(
        s,
        c,
        "respond_decision",
        decision_id=s.pending_decision.id,
        choices={"card_ids": ["cost0"]},
    )
    assert s.pending_decision and "magic_lamp" not in s.players[1].hand
    s, _ = command(
        s,
        c,
        "respond_decision",
        2,
        decision_id=s.pending_decision.id,
        choices={"card_ids": ["cost6"]},
    )
    assert s.combat is None and s.pending_decision is None
    assert "magic_lamp" in s.players[2].hand and "pretty_balloons" in s.players[1].hand


def test_impossible_escape_rejects_rat_and_avoids_roll():
    from tests.test_card_character import ability

    s, c = game(phase="combat.run_away")
    s.combat.monster_ids = ["crabs"]
    s.combat.escape_pending = {(1, "crabs")}
    s.players[1].in_play = ["rat_on_a_stick"]
    with pytest.raises(RuleError):
        ability(
            s, c, "rat_on_a_stick_escape", ["rat_on_a_stick"], {"monster_id": "crabs"}
        )
    rng = Random(1)
    before = rng.getstate()
    s, _ = combat.run_away(s, 1, "crabs", rng, c, now=NOW)
    assert rng.getstate() == before and s.combat is None


def test_automatic_escape_has_last_glue_opportunity():
    from tests.test_card_character import ability

    s, c = game(phase="combat.run_away")
    s.combat.escape_pending = {(1, "monster")}
    s.players[1].in_play = ["rat_on_a_stick"]
    s, _ = ability(
        s, c, "rat_on_a_stick_escape", ["rat_on_a_stick"], {"monster_id": "monster"}
    )
    assert s.combat and (1, "monster") in s.combat.automatic_escapes
    s, _ = play(
        s,
        c,
        "flask_of_glue",
        {"player_id": 1},
        {"attempt_id": s.combat.escape_roll_ids[(1, "monster")]},
        actor=2,
    )
    assert s.combat and (1, "monster") not in s.combat.automatic_escapes
    assert (1, "monster") in s.combat.escape_rolls


def test_invisibility_waits_for_failed_attempt_and_preserves_glue_window():
    s, c = game(phase="combat.run_away")
    s.combat.escape_pending = {(1, "monster")}
    s, _ = combat.run_away(s, 1, "monster", Random(1), c, now=NOW)
    s, _ = play(
        s,
        c,
        "invisibility_potion",
        choices={"attempt_id": s.combat.escape_roll_ids[(1, "monster")]},
    )
    assert s.combat and (1, "monster") in s.combat.automatic_escapes


def test_wall_requires_other_fighter_consent_before_automatic_escape():
    s, c = game(phase="combat.run_away")
    s.combat.fighter_ids = [1, 2]
    s.combat.helper_id = 2
    s.combat.escape_pending = {(1, "monster"), (2, "monster")}
    s, _ = play(s, c, "instant_wall", choices={"player_ids": [1, 2]})
    assert (
        s.pending_decision.kind == "wall_consent"
        and s.pending_decision.chooser_ids == [2]
    )
    s, _ = command(
        s,
        c,
        "respond_decision",
        2,
        decision_id=s.pending_decision.id,
        choices={"option": "decline"},
    )
    assert (1, "monster") in s.combat.automatic_escapes and (
        2,
        "monster",
    ) not in s.combat.automatic_escapes


def test_help_me_out_requires_immediate_legal_item_to_turn_loss_into_win():
    s, c = game(level=3)
    s.combat.monster_ids = ["bigfoot"]
    s.players[2].in_play = ["huge_rock"]
    s.players[1].level = 10
    s, _ = play(s, c, "help_me_out_here", {"player_id": 2, "card_id": "huge_rock"})
    assert (
        "huge_rock" in s.players[1].equipped and "huge_rock" not in s.players[2].in_play
    )


def test_amazon_cannot_be_killed_when_helping_fighter_is_female():
    s, c = game(level=5)
    s.combat.monster_ids = ["amazon"]
    s.players[2].character_sex = "female"
    s, _ = combat.ask_help(s, 1, 2, 0, [], c)
    s, _ = combat.accept_help(s, 2, c, now=NOW, rng=Random(1))
    assert s.combat is None and s.players[1].level == 5 and len(s.players[1].hand) == 7


def test_change_sex_pending_curse_makes_amazon_leave_without_kill_level():
    from tests.test_card_bad_stuff import respond

    s, c = game(level=5)
    s.players[1].character_sex = "male"
    s.combat.monster_ids = ["amazon"]
    s, _ = play(s, c, "curse_change_sex", {"player_id": 1}, actor=2)
    s, _ = respond(s, c)
    assert s.combat is None and s.players[1].level == 5 and len(s.players[1].hand) == 7


def test_hoard_additional_faceup_draws_offer_resurrection_again():
    from tests.test_card_bad_stuff import respond

    s, c = game(role="cleric", level=5)
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    s.combat.help_treasure_count = 0
    s.combat.monster_ids = ["lame_goblin"]
    s.treasure_deck = ["cost7", "cost6", "hoard"]
    s.treasure_discard = ["pretty_balloons"]
    s, _ = combat.resolve_rewards(s, c, Random(1), now=NOW)
    assert s.pending_decision.kind == "reward_draw"
    s, _ = respond(s, c, {"card_ids": []})
    assert s.pending_decision.kind == "reward_draw" and "hoard" in s.resolving_card_ids
    s, _ = respond(s, c, {"card_ids": ["cost0"]})
    assert s.combat is None and "pretty_balloons" in s.players[1].hand
    assert s.treasure_discard.count("hoard") == 1


def test_spent_removal_source_is_not_recycled_into_its_own_rewards():
    s, c = game()
    s.combat.monster_ids = ["lame_goblin"]
    s.treasure_deck = []
    s, _ = play(s, c, "pollymorph_potion", {"monster_id": "lame_goblin"})
    assert "pollymorph_potion" not in s.players[1].hand and s.treasure_discard == [
        "pollymorph_potion"
    ]


def test_dowsing_cannot_retrieve_reserved_monster_or_potion_midfight():
    s, c = game()
    s.combat.monster_ids = ["floating_nose", "lame_goblin"]
    s.players[1].hand += ["wand_of_dowsing"]
    s, _ = play(s, c, "potion_of_halitosis", {"monster_id": "floating_nose"})
    for cid in ["floating_nose", "potion_of_halitosis"]:
        old = deepcopy(s)
        with pytest.raises(RuleError):
            play(s, c, "wand_of_dowsing", {"card_id": cid})
        assert s == old


def test_pending_polymorph_treasure_is_lost_on_fleeing_remaining_foe():
    s, c = game(phase="combat.active")
    s.combat.monster_ids = ["lame_goblin", "bullrog"]
    s, _ = play(s, c, "pollymorph_potion", {"monster_id": "lame_goblin"})
    s, _ = combat.begin_escape(s, 1, c)
    s, _ = combat.run_away(s, 1, "bullrog", Random(5), c, now=NOW)
    assert s.combat is None and len(s.players[1].hand) == 6


def test_loaded_die_rejects_foreign_stale_and_boolean_without_state_rng_change():
    s, c = game(phase="combat.run_away")
    s.combat.escape_pending = {(1, "monster")}
    s.players[1].hand += ["loaded_die"]
    s.players[2].hand = ["loaded_die2"]
    from dataclasses import replace

    c["loaded_die2"] = replace(c["loaded_die"], id="loaded_die2")
    s, _ = combat.run_away(s, 1, "monster", Random(1), c, now=NOW)
    rid = s.combat.escape_roll_ids[(1, "monster")]
    for actor, cid, roll, value in [
        (1, "loaded_die", rid, True),
        (1, "loaded_die", rid, 0),
        (1, "loaded_die", "stale", 6),
        (2, "loaded_die2", rid, 6),
    ]:
        old = deepcopy(s)
        rng = Random(1)
        before = rng.getstate()
        with pytest.raises(RuleError):
            decide(
                s,
                Command(
                    "g",
                    actor,
                    "bad",
                    "play_card",
                    {
                        "now": NOW,
                        "card_id": cid,
                        "target": {},
                        "choices": {"roll_id": roll, "result": value},
                    },
                ),
                c,
                rng,
            )
        assert old == s and before == rng.getstate()


def test_configured_reaction_seconds_injected_before_intervention():
    s, c = game(level=9)
    s, _ = combat.declare_win(s, 1, c, NOW)
    s.players[2].hand = ["pretty_balloons"]
    s, _ = command(
        s,
        c,
        "play_card",
        2,
        card_id="pretty_balloons",
        target={},
        choices={"side": "fighters"},
        reaction_seconds=60,
    )
    assert s.combat.reaction_deadline == NOW + timedelta(seconds=60)


def test_lawyers_refuse_thief_and_exchange_is_optional_without_kill_rewards():
    s, c = game(role="thief", phase="turn.after_door", level=5)
    s.players[1].hand += ["lawyers"]
    s, _ = command(s, c, "seek_trouble", card_id="lawyers")
    assert s.pending_decision.kind == "loss_choice"
    s, _ = command(
        s,
        c,
        "respond_decision",
        decision_id=s.pending_decision.id,
        choices={"card_ids": []},
    )
    assert s.combat is None and s.players[1].level == 5


def test_explicit_identity_replacement_preserves_super_munchkin_and_usage():
    from dataclasses import replace

    s, c = game(role="wizard", phase="combat.active")
    s.players[1].in_play += ["super_munchkin"]
    s.players[1].hand += ["wizard2"]
    c["wizard2"] = replace(c["wizard"], id="wizard2")
    s.combat.ability_uses[(1, "wizard_charm", None)] = 1
    s, _ = command(s, c, "play_identity", card_id="wizard2", replace_id="wizard")
    assert (
        s.players[1].role_ids == ["wizard2"]
        and "super_munchkin" in s.players[1].in_play
    )
    assert (
        s.door_discard == ["wizard"]
        and s.combat.ability_uses[(1, "wizard_charm", None)] == 1
    )


def test_transfer_preserves_original_helpers_earned_treasure_share():
    s, c = game(level=5)
    s.combat.monster_ids = ["floating_nose", "lame_goblin"]
    s.combat.fighter_ids = [1, 2]
    s.combat.helper_id = 2
    s.combat.help_treasure_count = 1
    s.combat.help_item_ids = ["leather_armor"]
    s.players[1].in_play = ["leather_armor"]
    s.treasure_deck = ["cost6", "cost7", "pretty_balloons", "magic_missile"]
    s, _ = play(s, c, "potion_of_halitosis", {"monster_id": "floating_nose"})
    s, _ = play(s, c, "transferral_potion", {"player_id": 3})
    s, _ = combat.resolve_rewards(s, c, Random(1), now=NOW)
    assert len(s.players[2].hand) == 1
    assert len(s.players[1].hand) == 8
    assert len(s.players[3].hand) == 1
    assert "leather_armor" in s.players[2].in_play


def test_chicken_fire_bonus_uses_helper_weapon_and_fighter_side_only():
    s, c = game(level=4)
    s.combat.monster_ids = ["large_angry_chicken"]
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    s.players[2].in_play = ["staff_of_napalm", "wizard"]
    s.players[2].role_ids = ["wizard"]
    s.players[2].equipped = ["staff_of_napalm"]
    assert combat.monster_rewards(s, "large_angry_chicken", c)[0] == 2
    s.players[2].equipped = []
    s, _ = play(s, c, "flaming_poison_potion", choices={"side": "monsters"})
    assert combat.monster_rewards(s, "large_angry_chicken", c)[0] == 1


def test_no_pursuit_tuba_reward_commits_recycle_rng():
    s, c = game(level=3)
    s.combat.monster_ids = ["bullrog"]
    s.players[1].in_play = ["tuba_of_charm"]
    s.players[1].equipped = ["tuba_of_charm"]
    s.treasure_deck = []
    s.treasure_discard = ["cost6", "cost7"]
    s, _ = combat.begin_escape(s, 1, c)
    rng = Random(10)
    before = rng.getstate()
    s, _ = combat.run_away(s, 1, "bullrog", rng, c, now=NOW)
    assert len(s.players[1].hand) == 7 and rng.getstate() != before


def test_rat_virtual_mate_uses_original_printed_level():
    from tests.test_card_character import ability

    s, c = game(level=3)
    s.combat.monster_ids = ["amazon"]
    s.players[1].character_sex = "male"
    s, _ = play(s, c, "ancient", {"monster_id": "amazon"})
    s, _ = play(s, c, "mate", {"monster_id": "amazon"})
    ref = next(iter(s.combat.virtual_monsters))
    s.players[1].in_play = ["rat_on_a_stick"]
    s, _ = combat.begin_escape(s, 1, c)
    s, _ = ability(
        s, c, "rat_on_a_stick_escape", ["rat_on_a_stick"], {"monster_id": ref}
    )
    assert (1, ref) in s.combat.automatic_escapes


def test_one_cleric_manual_reward_choice_cannot_skip_other_cleric_response():
    from dataclasses import replace

    s, c = game(role="cleric", level=5)
    c["cleric2"] = replace(c["cleric"], id="cleric2")
    s.players[2].in_play = ["cleric2"]
    s.players[2].role_ids = ["cleric2"]
    s.players[2].hand = ["cost6"]
    s.treasure_deck = ["cost7"]
    s.treasure_discard = ["pretty_balloons", "magic_missile"]
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    s.combat.help_treasure_count = 1
    s, _ = combat.declare_win(s, 1, c, NOW)
    s, _ = command(
        s,
        c,
        "close_reaction",
        now=NOW + timedelta(seconds=30),
        resurrection_ids={1: ["cost0"]},
    )
    assert s.pending_decision and s.pending_decision.kind == "reward_draw"
    assert s.pending_decision.responses == {1: {"card_ids": ["cost0"]}}
    assert "magic_missile" not in s.players[1].hand


def test_public_close_cannot_choose_another_clerics_private_discard():
    s, c = game(role="cleric", level=5)
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    s, _ = combat.declare_win(s, 1, c, NOW)
    with pytest.raises(RuleError):
        command(
            s,
            c,
            "close_reaction",
            now=NOW + timedelta(seconds=30),
            resurrection_ids={2: []},
        )


@pytest.mark.parametrize("main_elf,helper_elf", [(False, True), (True, True)])
def test_potted_plant_one_extra_treasure_for_any_participating_elf(
    main_elf, helper_elf
):
    s, c = game(race="elf" if main_elf else None)
    s.combat.monster_ids = ["potted_plant"]
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    if helper_elf:
        from dataclasses import replace

        c["elf2"] = replace(c["elf"], id="elf2")
        s.players[2].in_play = ["elf2"]
        s.players[2].race_ids = ["elf2"]
    assert combat.monster_rewards(s, "potted_plant", c)[1] == 2


def test_forced_helper_leaves_when_later_level_gain_makes_winning_combat():
    s, c = game(level=8)
    s.players[2].level = 9
    s.players[1].in_play = ["kneepads_of_allure"]
    s.players[1].equipped = ["kneepads_of_allure"]
    s.combat.monster_ids = ["lame_goblin"]
    s, _ = command(s, c, "force_help", helper_id=2)
    assert s.combat.helper_id == 2
    s, _ = play(s, c, "boil_an_anthill", {"player_id": 1}, actor=3)
    assert (
        s.players[1].level == 9
        and s.combat.helper_id is None
        and s.combat.fighter_ids == [1]
    )


# Task 6 review round 1: reward ownership and character/turn/RNG boundaries.
@pytest.mark.parametrize("helper_count", [0, 1])
def test_review_i2_hoard_costs_respect_new_draw_ownership(helper_count):
    from dota_dungeon.core.card_rules import decision_options
    from tests.test_card_bad_stuff import respond

    s, c = game(role="cleric", level=5)
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    s.combat.help_treasure_count = helper_count
    s.treasure_deck = ["cost7", "cost6", "hoard", "pretty_balloons"]
    s.treasure_discard = ["magic_missile"]
    s, _ = combat.resolve_rewards(s, c, Random(1), now=NOW)
    s, _ = respond(s, c, {"card_ids": []})
    assert s.pending_decision.kind == "reward_draw"
    costs = decision_options(s, 1, c)["choices"]["card_ids"]
    if helper_count:
        assert "pretty_balloons" not in costs
        before, rng = deepcopy(s), Random(13)
        rng_before = rng.getstate()
        with pytest.raises(RuleError):
            decide(
                s,
                Command(
                    "g",
                    1,
                    "reserved-cost",
                    "respond_decision",
                    {
                        "decision_id": s.pending_decision.id,
                        "choices": {"card_ids": ["pretty_balloons"]},
                        "now": NOW,
                    },
                ),
                c,
                rng,
            )
        assert s == before and rng.getstate() == rng_before
        s, _ = respond(s, c, {"card_ids": ["cost0"]})
        assert "pretty_balloons" in s.players[2].hand
    else:
        assert "pretty_balloons" in costs
        s, _ = respond(s, c, {"card_ids": ["pretty_balloons"]})
        assert "pretty_balloons" in s.treasure_discard
    assert s.combat is None and s.pending_decision is None
    assert "magic_missile" in s.players[1].hand


@pytest.mark.parametrize("returning", [False, True])
def test_review_i5_transfer_applies_queued_penalty_preserving_combat_uses_and_rewards(
    returning,
):
    s, c = game(level=4)
    s.combat.monster_ids = ["floating_nose", "lame_goblin"]
    s, _ = play(s, c, "potion_of_halitosis", {"monster_id": "floating_nose"})
    earned = deepcopy(s.combat.pending_rewards)
    s.players[2].next_combat_penalty = 0 if returning else -5
    if returning:
        s.combat.character_penalties[2] = -5
    s.combat.ability_uses[(2, "warrior_berserk", None)] = 2
    s, _ = play(s, c, "transferral_potion", {"player_id": 2})
    assert combat.combat_strength(s, 2, c) == -2
    assert s.players[2].next_combat_penalty == 0
    assert s.combat.pending_rewards == earned
    assert s.combat.ability_uses[(2, "warrior_berserk", None)] == 2


def test_review_i6_after_combat_entitlement_ends_with_turn():
    s, c = game(level=4)
    s.players[1].hand = []
    s, _ = combat.resolve_rewards(s, c, Random(1), now=NOW)
    assert s.after_combat
    s, _ = command(s, c, "end_turn")
    assert s.active_user_id == 2 and not s.after_combat
    s.players[2].hand = ["mutilate_the_bodies"]
    before = deepcopy(s)
    with pytest.raises(RuleError):
        play(s, c, "mutilate_the_bodies", {"player_id": 2}, actor=2)
    assert s == before


@pytest.mark.parametrize("entry", ["open_door", "seek_trouble"])
def test_review_i6_new_combat_clears_previous_after_combat_entitlement(entry):
    s, c = game(phase="turn.prepare" if entry == "open_door" else "turn.after_door")
    s.after_combat = True
    s.door_deck = ["monster"]
    args = {}
    if entry == "seek_trouble":
        s.players[1].hand.append("monster")
        s.door_deck = []
        args["card_id"] = "monster"
    s, _ = command(s, c, entry, **args)
    assert s.combat and not s.after_combat


def test_review_i7_forced_female_help_amazon_recycle_uses_injected_rng():
    s, c = game(level=4)
    s.combat.monster_ids = ["amazon"]
    s.players[1].character_sex = "male"
    s.players[2].level = 5
    s.players[2].character_sex = "female"
    s.players[1].in_play = ["kneepads_of_allure"]
    s.players[1].equipped = ["kneepads_of_allure"]
    s.treasure_deck = []
    s.treasure_discard = ["cost6", "cost7"]
    cmd = Command("g", 1, "force-amazon", "force_help", {"helper_id": 2, "now": NOW})
    rng, replay_rng = Random(29), Random(29)
    before = rng.getstate()
    result, events = decide(s, cmd, c, rng)
    replay, replay_events = decide(deepcopy(s), cmd, c, replay_rng)
    assert result.combat is None
    assert rng.getstate() != before
    assert result == replay and events == replay_events
    assert rng.getstate() == replay_rng.getstate()
