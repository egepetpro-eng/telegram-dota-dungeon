import json
from pathlib import Path
from datetime import datetime, timezone
from random import Random
import pytest
from dota_dungeon.core.model import CardDef, CombatState, GameState, Player, RuleError
from dota_dungeon.core import combat, items, setup, turn
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def game(role=None, race=None, phase="combat.active", level=3):
    records = json.loads(
        (
            Path(__file__).parents[1]
            / "src/dota_dungeon/cards/data/classic-dota-v1/source-manifest.json"
        ).read_text(encoding="utf-8")
    )["cards"]
    catalog = {
        r["rule_key"]: CardDef.from_dict({**r, "id": r["rule_key"], "name": "renamed"})
        for r in records
    }
    catalog.update(
        {
            f"cost{i}": CardDef(f"cost{i}", "treasure", "item", "cost", value=500)
            for i in range(8)
        }
    )
    catalog["monster"] = CardDef(
        "monster",
        "door",
        "monster",
        "enemy",
        bonus=3,
        treasures=2,
        bad_stuff=[{"op": "lose_level", "amount": 2}],
    )
    p = Player(1, level=level, hand=[f"cost{i}" for i in range(8)])
    if role:
        p.role_ids = [role]
        p.in_play.append(role)
    if race:
        p.race_ids = [race]
        p.in_play.append(race)
    s = GameState(
        "g",
        1,
        1,
        phase,
        1,
        [1, 2, 3],
        {1: p, 2: Player(2, level=3), 3: Player(3, level=3)},
        treasure_deck=["cost7", "cost6"],
    )
    p.hand = p.hand[:6]
    s.card_decks = {k: v.deck for k, v in catalog.items()}
    if phase.startswith("combat"):
        s.combat = CombatState(fighter_ids=[1], monster_ids=["monster"])
    return s, catalog


def ability(s, c, key, costs, target=None, rng=None):
    return decide(
        s,
        Command(
            "g",
            1,
            key + str(costs) + str(target),
            "use_ability",
            {"ability_key": key, "cost_ids": costs, "target": target or {}, "now": NOW},
        ),
        c,
        rng or Random(2),
    )


def test_warrior_wins_ties_using_source_key():
    s, c = game("warrior")
    assert combat.declare_result(s, 1, c).outcome == "provisional_win"


def test_berserk_cost_and_three_per_combat():
    s, c = game("warrior")
    for i in range(3):
        s, _ = ability(s, c, "warrior_berserk", [f"cost{i}"])
    assert combat.combat_strength(s, 1, c) == 6
    with pytest.raises(RuleError):
        ability(s, c, "warrior_berserk", ["cost3"])
    assert s.players[1].hand == ["cost3", "cost4", "cost5"]


def test_cannot_discard_source_or_permanent_curse_for_ability():
    s, c = game("warrior")
    s.players[1].in_play.append("curse_change_sex")
    for cid in ["warrior", "curse_change_sex"]:
        with pytest.raises(RuleError):
            ability(s, c, "warrior_berserk", [cid])


def test_elf_helper_receives_kill_level_and_can_win():
    s, c = game()
    s.players[2].level = 9
    s.players[2].race_ids = ["elf"]
    s.players[2].in_play = ["elf"]
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    out, _ = combat.resolve_rewards(s, c, Random(2))
    assert out.players[2].level == 10
    assert out.phase == "game.finished"


def test_thief_backstab_is_per_victim():
    s, c = game("thief")
    s.combat.fighter_ids = [2, 3]
    s.active_user_id = 2
    s, _ = ability(s, c, "thief_backstab", ["cost0"], {"player_id": 2})
    s, _ = ability(s, c, "thief_backstab", ["cost1"], {"player_id": 3})
    assert s.combat.temporary_strength == {2: -2, 3: -2}
    with pytest.raises(RuleError):
        ability(s, c, "thief_backstab", ["cost2"], {"player_id": 2})


def test_thief_steals_small_carried_shot_without_equip_bonus():
    s, c = game("thief", phase="turn.prepare")
    s.players[2].in_play = ["magic_missile"]
    s, _ = ability(
        s,
        c,
        "thief_theft",
        ["cost0"],
        {"player_id": 2, "card_id": "magic_missile"},
        Random(5),
    )
    from tests.test_card_bad_stuff import respond
    s, _ = respond(s,c)
    assert "magic_missile" in s.players[1].in_play
    assert not s.players[2].in_play


def test_thief_cannot_steal_from_combat_participant_and_rng_atomic():
    s, c = game("thief")
    s.combat.fighter_ids = [2]
    s.players[2].in_play = ["magic_missile"]
    r = Random(5)
    before = r.getstate()
    with pytest.raises(RuleError):
        ability(
            s,
            c,
            "thief_theft",
            ["cost0"],
            {"player_id": 2, "card_id": "magic_missile"},
            r,
        )
    assert r.getstate() == before
    assert "cost0" in s.players[1].hand


def test_wizard_charm_entire_hand_no_levels_and_treasure_pipeline():
    s, c = game("wizard")
    s.players[1].hand = ["cost0", "cost1", "cost2"]
    out, _ = ability(
        s, c, "wizard_charm", s.players[1].hand.copy(), {"monster_id": "monster"}
    )
    assert out.players[1].level == 3
    assert set(out.players[1].hand) == {"cost6", "cost7"}
    assert out.combat is None


def test_wizard_charm_rewards_wait_for_whole_combat_success():
    s, c = game("wizard")
    s.players[1].hand = ["cost0", "cost1", "cost2"]
    c["m2"] = CardDef("m2", "door", "monster", "second", bonus=20, treasures=1)
    s.combat.monster_ids.append("m2")
    s, _ = ability(
        s, c, "wizard_charm", s.players[1].hand.copy(), {"monster_id": "monster"}
    )
    assert not s.players[1].hand
    assert s.combat is not None
    s, _ = combat.resolve_rewards(s, c, Random(1))
    assert s.players[1].level == 4
    assert len(s.players[1].hand) == 3


def test_cleric_turn_undead_requires_participation_and_undead():
    s, c = game("cleric")
    with pytest.raises(RuleError):
        ability(s, c, "cleric_turn_undead", ["cost0"])
    from dataclasses import replace

    c["monster"] = replace(c["monster"], tags=("undead",))
    s, _ = ability(s, c, "cleric_turn_undead", ["cost0"])
    assert combat.combat_strength(s, 1, c) == 6


def test_failed_escape_is_stored_before_bad_stuff_and_halfling_can_retry():
    s, c = game(race="halfling", phase="combat.run_away")
    s.combat.escape_pending = {(1, "monster")}
    s, _ = combat.run_away(s, 1, "monster", Random(2), c)
    assert s.players[1].level == 3
    assert s.combat.escape_rolls[(1, "monster")] == 1
    s, _ = ability(
        s, c, "halfling_escape_retry", ["cost0"], {"monster_id": "monster"}, Random(5)
    )
    assert s.combat.escape_rolls[(1, "monster")] == 5
    with pytest.raises(RuleError):
        ability(s, c, "halfling_escape_retry", ["cost1"], {"monster_id": "monster"})
    s, _ = combat.resolve_escape(s, 1, "monster", c)
    assert s.players[1].level == 3
    assert s.combat is None


def test_wizard_flight_after_roll_adds_at_most_three():
    s, c = game("wizard", phase="combat.run_away")
    s.combat.escape_pending = {(1, "monster")}
    with pytest.raises(RuleError):
        ability(s, c, "wizard_flight", ["cost0"], {"monster_id": "monster"})
    s, _ = combat.run_away(s, 1, "monster", Random(2), c)
    for i in range(3):
        s, _ = ability(s, c, "wizard_flight", [f"cost{i}"], {"monster_id": "monster"})
    with pytest.raises(RuleError):
        ability(s, c, "wizard_flight", ["cost3"], {"monster_id": "monster"})
    s, _ = combat.resolve_escape(s, 1, "monster", c)
    assert s.players[1].level == 1


def test_cleric_resurrects_top_door_discard_before_draw():
    s, c = game("cleric", phase="turn.prepare")
    s.door_deck = ["lame_goblin"]
    s.door_discard = ["monster"]
    s.players[1].hand = ["cost0"]
    out, _ = ability(s, c, "cleric_resurrection", ["cost0"], {"deck": "door"})
    assert out.combat.monster_ids == ["monster"]
    assert out.door_deck == ["lame_goblin"]
    assert out.treasure_discard == ["cost0"]


def test_optional_game_sex_is_lobby_only_and_seeded_default():
    s, c = game(phase="lobby")
    s.players[1].ready = s.players[2].ready = s.players[3].ready = True
    s, _ = setup.set_character_sex(s, 1, "female")
    a, _ = setup.start(s, 1, c, Random(4))
    b, _ = setup.start(s, 1, c, Random(4))
    assert a.players[1].character_sex == "female"
    assert [p.character_sex for p in a.players.values()] == [
        p.character_sex for p in b.players.values()
    ]
    with pytest.raises(RuleError):
        setup.set_character_sex(a, 1, "male")


def test_sex_curse_penalty_only_next_combat():
    from dota_dungeon.core.effects import apply_effects

    s, c = game(phase="turn.prepare")
    s.players[1].character_sex = "male"
    s, _ = apply_effects(s, 1, c["curse_change_sex"].effects, c)
    assert s.players[1].character_sex == "female"
    s.phase = "turn.after_door"
    s.players[1].hand.append("monster")
    s, _ = turn.seek_trouble(s, 1, "monster", c)
    assert combat.combat_strength(s, 1, c) == -2
    s, _ = combat.resolve_rewards(s, c)
    s.phase = "turn.after_door"
    s.players[1].hand.append("monster")
    s, _ = turn.seek_trouble(s, 1, "monster", c)
    assert combat.combat_strength(s, 1, c) == 4


def test_conditional_enemy_bonus_and_item_bonus_share_public_totals():
    s, c = game(race="elf")
    s.combat.monster_ids = ["squidzilla"]
    s.players[1].in_play.append("horny_helmet")
    s.players[1].equipped = ["horny_helmet"]
    assert combat.combat_totals(s, c) == (6, 22)


def test_helper_cleric_resurrects_own_faceup_reward_entitlement():
    s, c = game()
    s.combat.fighter_ids = [1, 2]
    s.combat.helper_id = 2
    s.combat.help_treasure_count = 1
    s.players[2].role_ids = ["cleric"]
    s.players[2].in_play = ["cleric"]
    s.players[2].hand = ["cost3"]
    s.treasure_discard = ["magic_missile"]
    out, _ = combat.resolve_rewards(s, c, Random(2), resurrection_ids={2: ["cost3"]})
    assert out.players[2].hand == ["magic_missile"]
    assert out.players[1].hand[-1] == "cost6"
    assert out.treasure_discard == ["cost3"]


def test_cleric_resurrection_rejects_facedown_and_atomic_bad_costs():
    from dota_dungeon.core.draw import draw_cards

    s, c = game("cleric")
    s.treasure_discard = ["magic_missile"]
    r = Random(1)
    before = r.getstate()
    for costs, faceup in [
        (["cost0"], False),
        (["cost0", "cost0"], True),
        (["cost0", "cost1"], True),
    ]:
        with pytest.raises(RuleError):
            draw_cards(s, 1, "treasure", 1, faceup, c, r, resurrection_ids=costs)
    assert s.treasure_discard == ["magic_missile"]
    assert r.getstate() == before


def test_same_deck_resurrection_takes_old_top_before_discarding_cost():
    s, c = game("cleric", phase="turn.prepare")
    s.door_discard = ["monster"]
    s.door_deck = ["lame_goblin"]
    s.players[1].hand = ["thief"]
    out, _ = ability(s, c, "cleric_resurrection", ["thief"], {"deck": "door"})
    assert out.combat.monster_ids == ["monster"]
    assert out.door_discard == ["thief"]


def test_theft_failure_loses_level_and_pays_cost():
    s, c = game("thief", phase="turn.prepare")
    s.players[2].in_play = ["magic_missile"]
    out, _ = ability(
        s,
        c,
        "thief_theft",
        ["cost0"],
        {"player_id": 2, "card_id": "magic_missile"},
        Random(2),
    )
    from tests.test_card_bad_stuff import respond
    out, _ = respond(out,c)
    assert out.players[1].level == 2
    assert "cost0" in out.treasure_discard
    assert out.players[2].in_play == ["magic_missile"]


def test_nonparticipant_wizard_cannot_charm_and_whole_hand_minimum_three():
    s, c = game("wizard")
    s.players[1].hand = ["cost0", "cost1"]
    with pytest.raises(RuleError):
        ability(
            s, c, "wizard_charm", s.players[1].hand.copy(), {"monster_id": "monster"}
        )
    s.players[1].hand.append("cost2")
    s.combat.fighter_ids = [2]
    with pytest.raises(RuleError):
        ability(
            s, c, "wizard_charm", s.players[1].hand.copy(), {"monster_id": "monster"}
        )


def test_ability_idempotency_and_reaction_window_restart():
    s, c = game("warrior")
    s.combat.reaction_deadline = NOW
    s.combat.passes = {2}
    out, events = ability(s, c, "warrior.berserk", ["cost0"])
    again, repeated = ability(out, c, "warrior.berserk", ["cost0"])
    assert again == out
    assert not repeated
    assert not out.combat.passes
    assert out.combat.reaction_deadline > NOW


def test_character_handler_validators_are_closed_and_bootstrap_without_engine():
    from dota_dungeon.core import card_rules
    from dota_dungeon.cards.schema import validate_mechanics

    s, c = game()
    for key in [
        "warrior",
        "thief",
        "wizard",
        "cleric",
        "elf",
        "dwarf",
        "halfling",
        "half_breed",
        "super_munchkin",
        "hireling",
        "cheat",
        "rat_on_a_stick",
    ]:
        card = c[key]
        mechanics = {
            name: getattr(card, name)
            for name in [
                "deck",
                "kind",
                "value",
                "bonus",
                "slots",
                "size",
                "effects",
                "tags",
                "treasures",
                "levels",
                "bad_stuff",
                "play_phases",
                "target_rule",
                "restrictions",
                "conditions",
                "abilities",
                "trigger",
            ]
        }
        mechanics["tags"] = list(mechanics["tags"])
        mechanics["play_phases"] = list(mechanics["play_phases"])
        validate_mechanics(mechanics, key)
    registered = card_rules.ABILITY_HANDLERS["warrior_berserk"]
    valid = {k: v for k, v in c["warrior"].abilities[0].items() if k != "key"}
    from copy import deepcopy

    invalid = deepcopy(valid)
    invalid["limit"]["max_uses"] = True
    with pytest.raises(ValueError):
        registered.validate_args(invalid)
    with pytest.raises(ValueError):
        card_rules.CONDITION_HANDLERS["monster_bonus"].validate_args(
            {"race_any": ["elf"], "amount": 4, "extra": True}
        )


def test_tuba_draws_one_private_treasure_after_user_escapes_whole_combat():
    s, c = game(phase="combat.run_away")
    s.players[1].in_play = ["tuba_of_charm"]
    s.players[1].equipped = ["tuba_of_charm"]
    s.combat.monster_ids = ["monster", "lame_goblin"]
    s.combat.escape_pending = {(1, "monster"), (1, "lame_goblin")}
    s, _ = combat.run_away(s, 1, "monster", Random(4), c)
    assert len(s.players[1].hand) == 6
    s, _ = combat.resolve_escape(s, 1, "monster", c, Random(4))
    s, _ = combat.run_away(s, 1, "lame_goblin", Random(5), c)
    s, events = combat.resolve_escape(s, 1, "lame_goblin", c, Random(5))
    assert len(s.players[1].hand) == 7
    assert s.combat is None
    assert any(e.name == "card.drawn" and e.audience == "user:1" for e in events)


def test_tuba_no_reward_for_any_failed_escape():
    s, c = game(phase="combat.run_away")
    s.players[1].in_play = ["tuba_of_charm"]
    s.players[1].equipped = ["tuba_of_charm"]
    s.combat.escape_pending = {(1, "monster")}
    s.combat.escape_rolls[(1, "monster")] = 1
    s, _ = combat.resolve_escape(s, 1, "monster", c)
    assert len(s.players[1].hand) == 6
    assert s.players[1].level == 1


def test_sex_curse_applies_current_participating_combat():
    from dota_dungeon.core.effects import apply_effects

    s, c = game()
    s.players[1].character_sex = "female"
    s, _ = apply_effects(s, 1, c["curse_change_sex"].effects, c)
    assert combat.combat_strength(s, 1, c) == -2
    assert s.players[1].next_combat_penalty == 0
    s, _ = apply_effects(s, 2, c["curse_change_sex"].effects, c)
    assert s.players[2].next_combat_penalty == -5


def test_simultaneous_cleric_rewards_reserve_old_discard_tops_before_both_costs():
    s, c = game("cleric")
    s.players[1].hand = ["cost0"]
    s.players[2].role_ids = ["cleric"]
    s.players[2].in_play = ["cleric"]
    s.players[2].hand = ["cost3"]
    s.combat.fighter_ids = [1, 2]
    s.combat.helper_id = 2
    s.combat.help_treasure_count = 1
    s.treasure_discard = ["friendship_potion", "magic_missile"]
    out, _ = combat.resolve_rewards(
        s, c, Random(2), resurrection_ids={1: ["cost0"], 2: ["cost3"]}
    )
    assert out.players[2].hand == ["magic_missile"]
    assert out.players[1].hand == ["friendship_potion"]
    assert set(out.treasure_discard) == {"cost0", "cost3"}


def test_elf_helper_gets_one_level_per_kill_not_monster_level_rewards():
    s, c = game()
    s.players[2].race_ids = ["elf"]
    s.players[2].in_play = ["elf"]
    s.combat.helper_id = 2
    s.combat.fighter_ids = [1, 2]
    from dataclasses import replace

    c["monster"] = replace(c["monster"], levels=2)
    s.combat.monster_ids = ["monster", "lame_goblin"]
    out, _ = combat.resolve_rewards(s, c, Random(2))
    assert out.players[1].level == 6
    assert out.players[2].level == 5


def test_class_and_escape_counters_do_not_leak_between_combats_or_monsters():
    s, c = game("warrior")
    s, _ = ability(s, c, "warrior_berserk", ["cost0"])
    s, _ = combat.resolve_rewards(s, c, Random(2))
    s.phase = "turn.after_door"
    s.players[1].hand.append("monster")
    s, _ = turn.seek_trouble(s, 1, "monster", c)
    s, _ = ability(s, c, "warrior_berserk", ["cost1"])
    assert s.combat.temporary_strength[1] == 1
    s, c = game("wizard", phase="combat.run_away")
    s.combat.monster_ids = ["monster", "lame_goblin"]
    s.combat.escape_pending = {(1, "monster"), (1, "lame_goblin")}
    s, _ = combat.run_away(s, 1, "monster", Random(2), c)
    s, _ = ability(s, c, "wizard_flight", ["cost0"], {"monster_id": "monster"})
    s, _ = combat.resolve_escape(s, 1, "monster", c, Random(2))
    s, _ = combat.run_away(s, 1, "lame_goblin", Random(2), c)
    s, _ = ability(s, c, "wizard_flight", ["cost1"], {"monster_id": "lame_goblin"})
    assert s.combat.escape_bonuses == {(1, "monster"): 1, (1, "lame_goblin"): 1}


def test_resurrection_and_costs_preserve_one_physical_zone():
    s, c = game("cleric", phase="turn.prepare")
    s.door_deck = ["lame_goblin"]
    s.door_discard = ["monster"]
    s.players[1].hand = ["cost0"]
    out, _ = ability(s, c, "cleric_resurrection", ["cost0"], {"deck": "door"})
    physical = (
        out.door_deck + out.treasure_deck + out.door_discard + out.treasure_discard
    )
    physical += (
        sum((p.hand + p.in_play for p in out.players.values()), [])
        + out.combat.monster_ids
        + out.combat.played_card_ids
        + out.combat.charmed_monster_ids
    )
    assert len(physical) == len(set(physical))


@pytest.mark.parametrize(
    "key,source",
    [("rat_on_a_stick_escape", "rat_on_a_stick"), ("hireling_escape", "hireling")],
)
def test_automatic_escape_rejects_stored_roll_and_preserves_state_rng(key, source):
    from copy import deepcopy

    s, c = game("wizard", phase="combat.run_away")
    s.players[1].in_play.append(source)
    s.combat.escape_pending = {(1, "monster")}
    s.combat.escape_rolls[(1, "monster")] = 1
    before = deepcopy(s)
    r = Random(2)
    rngbefore = r.getstate()
    with pytest.raises(RuleError, match="roll"):
        ability(s, c, key, [source], {"monster_id": "monster"}, r)
    assert s == before
    assert r.getstate() == rngbefore


def test_escape_window_does_not_reveal_any_hidden_hand_card():
    from copy import deepcopy

    states = []
    for owner, hidden in [
        (2, []),
        (2, ["loaded_die"]),
        (1, ["loaded_die"]),
        (3, ["flask_of_glue"]),
    ]:
        s, c = game(phase="combat.run_away")
        s.combat.escape_pending = {(1, "monster")}
        s.players[owner].hand = hidden
        out, events = combat.run_away(s, 1, "monster", Random(2), c)
        states.append(
            (out.phase, out.combat.escape_rolls if out.combat else {}, events)
        )
    assert all(value == states[0] for value in states)
    assert states[0][1] == {(1, "monster"): 1}


def test_unresolved_roll_blocks_other_escape_and_unrelated_engine_actions():
    from copy import deepcopy

    s, c = game("wizard", phase="combat.run_away")
    s.combat.monster_ids.append("lame_goblin")
    s.combat.escape_pending = {(1, "monster"), (1, "lame_goblin")}
    s.combat.escape_rolls[(1, "monster")] = 1
    before = deepcopy(s)
    r = Random(2)
    rngbefore = r.getstate()
    for command in [
        Command("g", 1, "next", "run_away", {"monster_id": "lame_goblin"}),
        Command("g", 1, "discard", "discard_identity", {"card_id": "wizard"}),
        Command(
            "g",
            1,
            "resurrect",
            "use_ability",
            {
                "ability_key": "cleric_resurrection",
                "target": {"deck": "treasure"},
                "cost_ids": ["cost0"],
                "now": NOW,
            },
        ),
    ]:
        with pytest.raises(RuleError, match="roll"):
            decide(s, command, c, r)
    assert s == before
    assert r.getstate() == rngbefore


def test_after_roll_policy_admits_only_own_class_actions_and_exact_future_card_timing():
    s, c = game("wizard", phase="combat.run_away")
    s.combat.escape_pending = {(1, "monster")}
    s.combat.escape_rolls[(1, "monster")] = 1
    policy = combat.validate_escape_action
    for action, key, target in [
        ("use_ability", "wizard_flight", {"monster_id": "monster"}),
        ("use_ability", "halfling_escape_retry", {"monster_id": "monster"}),
        ("play_card", "loaded_die", {}),
        ("play_card", "invisibility_potion", {}),
        ("play_card", "magic_lamp", {"monster_id": "monster"}),
    ]:
        policy(s, 1, action, target, c, rule_key=key)
    for actor, action, key, target in [
        (2, "play_card", "loaded_die", {}),
        (2, "use_ability", "wizard_flight", {"monster_id": "monster"}),
        (1, "play_card", "flask_of_glue", {"player_id": 1}),
        (1, "play_card", "curse_change_sex", {"player_id": 1}),
    ]:
        with pytest.raises(RuleError, match="roll"):
            policy(s, actor, action, target, c, rule_key=key)
    s.combat.escape_rolls[(1, "monster")] = 6
    policy(s, 2, "play_card", {"player_id": 1}, c, rule_key="flask_of_glue")
    for key, target in [
        ("invisibility_potion", {}),
        ("magic_lamp", {"monster_id": "monster"}),
    ]:
        with pytest.raises(RuleError, match="roll"):
            policy(s, 1, "play_card", target, c, rule_key=key)
    from dota_dungeon.core.card_rules import SPECIAL_HANDLERS

    assert all(
        key in SPECIAL_HANDLERS
        for key in ["loaded_die", "invisibility_potion", "magic_lamp", "flask_of_glue"]
    )
