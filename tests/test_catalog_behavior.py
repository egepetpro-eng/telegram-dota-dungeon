"""Independent literal source expectations exercised against the installed release.

No source effect/condition/value descriptor supplies an expected result here.
Controlled fixtures relocate real cards, then every tested action uses decide.
Coverage acceptance is tracked separately; a passing baseline does not certify
an unimplemented distinctive subcase in the behavior ledger.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from random import Random
from itertools import combinations

import pytest

from dota_dungeon.cards.installed import validate_installed_release
from dota_dungeon.core.combat import combat_strength, combat_totals
from dota_dungeon.core.engine import decide
from dota_dungeon.core.model import Command, RuleError
from dota_dungeon.core.setup import new_lobby

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


class Dice(Random):
    """Reproducible real RNG whose explicit die stream survives transaction copies."""
    def __init__(self, *dice):
        super().__init__(37)
        self.dice = list(dice)

    def randint(self, a, b):
        if (a, b) == (1, 6):
            assert self.dice, "unexpected extra die roll"
            return self.dice.pop(0)
        return super().randint(a, b)

    def getstate(self):
        return super().getstate(), tuple(self.dice)

    def setstate(self, state):
        base, dice = state
        super().setstate(base)
        self.dice = list(dice)


@pytest.fixture(scope="module")
def release():
    # Deliberately strict: pending production handlers are a failure, not a skip.
    return validate_installed_release()


def assert_zones(state, catalog):
    zones = [state.door_deck, state.treasure_deck,
             state.door_discard, state.treasure_discard]
    zones.append(getattr(state, "resolving_card_ids", []))
    zones.extend(p.hand for p in state.players.values())
    zones.extend(p.in_play for p in state.players.values())
    zones.extend(state.corpse.values())
    if state.combat:
        c = state.combat
        virtual = getattr(c, "virtual_monsters", {})
        zones.append([cid for cid in c.monster_ids if cid not in virtual])
        zones.append(c.played_card_ids)
        zones.append(c.charmed_monster_ids)
        zones.append(getattr(c, "retired_monster_ids", []))
    assert Counter(cid for zone in zones for cid in zone) == Counter(catalog.keys())


class Game:
    def __init__(self, release, *, level=3, count=3, seed=37):
        self.catalog = release.catalog
        self.state = new_lobby("behavior", -100, 1, self.catalog)
        self.rng = Random(seed)
        self.seq = 0
        for uid in range(1, count + 1):
            self.do(uid, "join")
            self.do(uid, "set_character_sex", character_sex="male")
            self.do(uid, "ready", ready=True)
        # Fixture is a legal prepared turn with controlled, fully conserved piles.
        self.state.phase = "turn.prepare"
        self.state.active_user_id = 1
        self.state.turn_number = 1
        for p in self.state.players.values():
            p.level = level

    def command(self, actor, action, **args):
        self.seq += 1
        return Command(self.state.game_id, actor, f"behavior:{self.seq}",
                       action, {"now": NOW, **args})

    def do(self, actor, action, **args):
        before_hidden = {cid for p in self.state.players.values() for cid in p.hand}
        self.state, events = decide(self.state, self.command(actor, action, **args),
                                    self.catalog, self.rng)
        assert_zones(self.state, self.catalog)
        still_hidden = before_hidden & {cid for p in self.state.players.values() for cid in p.hand}
        for event in events:
            if event.audience == "group":
                assert not (still_hidden & strings_in(event.data)), (action, event)
        return events

    def reject(self, actor, action, **args):
        before, rng_before = deepcopy(self.state), self.rng.getstate()
        with pytest.raises(RuleError):
            self.do(actor, action, **args)
        assert self.state == before
        assert self.rng.getstate() == rng_before

    def give(self, key, actor=1, copy=1):
        cid = f"{key}:{copy}"
        pile = (self.state.door_deck if self.state.card_decks[cid] == "door"
                else self.state.treasure_deck)
        pile.remove(cid)
        self.state.players[actor].hand.append(cid)
        assert_zones(self.state, self.catalog)
        return cid

    def play(self, key, actor=1, target=None, **args):
        cid = self.give(key, actor)
        self.do(actor, "play_card", card_id=cid, target=target or {}, **args)
        return cid

    def identity(self, key, actor=1, copy=1):
        cid = self.give(key, actor, copy)
        self.do(actor, "play_identity", card_id=cid)
        return cid

    def equip(self, key, actor=1):
        cid = self.give(key, actor)
        self.do(actor, "equip", card_id=cid)
        return cid

    def open(self, key):
        cid = f"{key}:1"
        self.state.door_deck.remove(cid)
        self.state.door_deck.append(cid)
        self.do(1, "open_door")
        return cid

    def win(self):
        self.do(1, "declare_win")
        for uid in self.state.order:
            if uid != 1:
                self.do(uid, "pass_reaction")
        events = self.do(1, "close_reaction")
        events.extend(self.decline_windows())
        return events

    def safe_treasures(self):
        # Literal non-trigger reward tops; no expected count comes from catalog.
        safe = ["1_000_gold_pieces", "boil_an_anthill", "bribe_gm_with_food",
                "convenient_addition_error", "invoke_obscure_rules",
                "potion_of_general_studliness", "whine_at_the_gm",
                "steal_a_level", "mutilate_the_bodies", "kill_the_hireling"]
        for key in reversed(safe):
            cid = key + ":1"
            if cid in self.state.treasure_deck:
                self.state.treasure_deck.remove(cid)
                self.state.treasure_deck.append(cid)

    def respond(self, actor, **choices):
        pending = self.state.pending_decision
        assert pending is not None
        return self.do(actor, "respond_decision", decision_id=pending.id, choices=choices)

    def decline_windows(self):
        events = []
        for _ in range(30):
            pending = getattr(self.state, "pending_decision", None)
            if pending is None or pending.kind == "loss_choice":
                return events
            assert pending.kind in {"curse_response", "die_response", "reward_draw"}
            for actor in pending.chooser_ids:
                if self.state.pending_decision is None or self.state.pending_decision.id != pending.id:
                    break
                if actor not in pending.responses:
                    events.extend(self.respond(actor, **({"card_ids": []} if pending.kind == "reward_draw" else {})))
        raise AssertionError("response windows did not converge")

    def lose_to(self, key, *, die=1, bad_die=None):
        monster = self.open(key)
        self.decline_windows()
        # Low monsters require real intervention before the fighter may flee.
        for enhancer in ("humongous", "ancient", "enraged"):
            fighter, enemy = combat_totals(self.state, self.catalog)
            if fighter <= enemy:
                break
            self.play(enhancer, actor=2, target={"monster_id": monster})
        self.rng = Dice(die, *([] if bad_die is None else [bad_die]))
        self.do(1, "begin_escape")
        self.do(1, "run_away", monster_id=monster)
        self.decline_windows()
        if self.state.combat and (1, monster) in self.state.combat.escape_rolls:
            self.do(1, "resolve_escape", monster_id=monster, now=NOW + timedelta(minutes=10))
            self.decline_windows()
        return monster


def strings_in(value):
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(strings_in(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple, set)):
        return set().union(*(strings_in(v) for v in value)) if value else set()
    return set()


# Printed bonus; prerequisite; incompatible identity/trait; printed slot/size.
# The table is transcribed from the accepted independent source preparation.
EQUIPMENT = {
    "bad_ass_bandana": (3, None, "elf", "head", False),
    "boots_of_butt_kicking": (2, None, None, "footwear", False),
    "boots_of_running_really_fast": (0, None, None, "footwear", False),
    "bow_with_ribbons": (4, "elf", "human", "two_hands", False),
    "broad_sword": (3, "female", "male", "hand", False),
    "buckler_of_swashing": (2, None, None, "hand", False),
    "chainsaw_of_bloody_dismemberment": (3, None, None, "two_hands", True),
    "cheese_grater_of_peace": (3, "cleric", "wizard", "hand", False),
    "cloak_of_obscurity": (4, "thief", "cleric", None, False),
    "dagger_of_treachery": (3, "thief", "wizard", "hand", False),
    "eleven_foot_pole": (1, None, None, "two_hands", False),
    "flaming_armor": (2, None, None, "armor", False),
    "gentleman_s_club": (3, "male", "female", "hand", False),
    "hammer_of_kneecapping": (4, "dwarf", "human", "hand", False),
    "helm_of_courage": (1, None, None, "head", False),
    "horny_helmet": (1, None, None, "head", False),
    "huge_rock": (3, None, None, "two_hands", True),
    "kneepads_of_allure": (0, "wizard", "cleric", None, False),
    "leather_armor": (1, None, None, "armor", False),
    "limburger_and_anchovy_sandwich": (3, "halfling", "human", None, False),
    "mace_of_sharpness": (4, "cleric", "warrior", "hand", False),
    "mithril_armor": (3, "warrior", "wizard", "armor", True),
    "pantyhose_of_giant_strength": (3, "wizard", "warrior", None, False),
    "pointy_hat_of_power": (3, "wizard", "cleric", "head", False),
    "rapier_of_unfairness": (3, "elf", "human", "hand", False),
    "rat_on_a_stick": (1, None, None, "hand", False),
    "sandals_of_protection": (0, None, None, "footwear", False),
    "shield_of_ubiquity": (4, "warrior", "human", "hand", True),
    "short_wide_armor": (3, "dwarf", "elf", "armor", False),
    "singing_dancing_sword": (2, "wizard", "thief", None, False),
    "slimy_armor": (1, None, None, "armor", False),
    "sneaky_bastard_sword": (2, None, None, "hand", False),
    "spiky_knees": (1, None, None, None, False),
    "staff_of_napalm": (5, "wizard", "warrior", "hand", False),
    "stepladder": (3, "halfling", "human", None, True),
    "swiss_army_polearm": (4, None, "elf", "two_hands", True),
    "tuba_of_charm": (0, None, None, "hand", True),
}
BOOSTS = {"cotion_of_ponfusion": 3, "electric_radioactive_acid_potion": 5,
          "flaming_poison_potion": 3, "freezing_explosive_potion": 3,
          "magic_missile": 5, "nasty_tasting_sports_drink": 2,
          "potion_of_idiotic_bravery": 2, "pretty_balloons": 5,
          "sleep_potion": 2}
LEVELS = ("1_000_gold_pieces", "boil_an_anthill", "bribe_gm_with_food",
          "convenient_addition_error", "invoke_obscure_rules",
          "potion_of_general_studliness")
ENHANCERS = {"ancient": (20, 5), "baby": (5, 2), "enraged": (15, 4),
             "humongous": (20, 5), "intelligent": (15, 4)}
MONSTERS = {
    "3_872_orcs": (10, 3, 1), "amazon": (8, 2, 1), "bigfoot": (12, 3, 1),
    "bullrog": (18, 5, 2), "crabs": (1, 1, 1), "drooling_slime": (1, 1, 1),
    "face_sucker": (8, 2, 1), "floating_nose": (10, 3, 1), "flying_frogs": (2, 1, 1),
    "gazebo": (8, 2, 1), "gelatinous_octahedron": (2, 1, 1), "ghoulfiends": (8, 2, 1),
    "harpies": (4, 2, 1), "hippogriff": (16, 4, 2), "insurance_salesman": (14, 4, 1),
    "king_tut": (16, 4, 2), "lame_goblin": (1, 1, 1), "large_angry_chicken": (2, 1, 1),
    "lawyers": (6, 2, 1), "leperchaun": (4, 2, 1), "maul_rat": (1, 1, 1),
    "mr_bones": (2, 1, 1), "net_troll": (10, 3, 1), "pit_bull": (2, 1, 1),
    "platycore": (6, 2, 1), "plutonium_dragon": (20, 5, 2), "potted_plant": (1, 1, 1),
    "pukachu": (6, 2, 1), "shrieking_geek": (6, 2, 1), "snails_on_speed": (4, 2, 1),
    "squidzilla": (18, 4, 2), "stoned_golem": (14, 4, 1), "tongue_demon": (12, 3, 1),
    "undead_horse": (4, 2, 1), "unspeakably_awful_indescribable_horror": (14, 4, 1),
    "wannabe_vampire": (12, 3, 1), "wight_brothers": (16, 4, 2),
}
MONSTER_IDENTITY_BONUSES = {
    "3_872_orcs": ("dwarf", 16), "bigfoot": ("dwarf", 15),
    "drooling_slime": ("elf", 5), "face_sucker": ("elf", 14),
    "harpies": ("wizard", 9), "leperchaun": ("elf", 9),
    "maul_rat": ("cleric", 4), "platycore": ("wizard", 12),
    "shrieking_geek": ("warrior", 12), "squidzilla": ("elf", 22),
    "tongue_demon": ("cleric", 16), "undead_horse": ("dwarf", 9),
    "unspeakably_awful_indescribable_horror": ("warrior", 18),
}
BAD_LEVELS = {"amazon": 4, "drooling_slime": 6, "face_sucker": 6,
              "floating_nose": 4, "flying_frogs": 5, "gazebo": 4,
              "harpies": 5, "lame_goblin": 6, "large_angry_chicken": 6,
              "maul_rat": 6, "mr_bones": 4, "pit_bull": 5,
              "tongue_demon": 5, "undead_horse": 5, "wannabe_vampire": 4,
              "wight_brothers": 1}
CURSES = (
    "curse_change_class", "curse_change_race", "curse_change_sex",
    "curse_chicken_on_your_head", "curse_duck_of_doom", "curse_income_tax",
    "curse_lose_a_big_item", "curse_lose_a_level", "curse_lose_a_small_item",
    "curse_lose_the_armor_you_are_wearing", "curse_lose_the_footgear_you_are_wearing",
    "curse_lose_the_headgear_you_are_wearing", "curse_lose_two_cards",
    "curse_lose_your_class", "curse_lose_your_race", "curse_malign_mirror",
    "truly_obnoxious_curse",
)
CHARACTERS = ("cleric", "dwarf", "elf", "halfling", "thief", "warrior", "wizard")
SPECIAL_LEVELS = ("kill_the_hireling", "mutilate_the_bodies", "steal_a_level", "whine_at_the_gm")
SPECIALS = ("cheat", "divine_intervention", "half_breed", "help_me_out_here",
            "illusion", "mate", "out_to_lunch", "super_munchkin", "wandering_monster",
            "hireling", "hoard", "really_impressive_title")
EXCEPTIONAL_ITEMS = ("doppleganger", "flask_of_glue", "friendship_potion", "instant_wall",
                     "invisibility_potion", "loaded_die", "magic_lamp", "pollymorph_potion",
                     "potion_of_halitosis", "transferral_potion", "wand_of_dowsing",
                     "wishing_ring", "yuppie_water")
PRICES = {
    "bad_ass_bandana": 400, "boots_of_butt_kicking": 400, "boots_of_running_really_fast": 400,
    "bow_with_ribbons": 800, "broad_sword": 400, "buckler_of_swashing": 400,
    "chainsaw_of_bloody_dismemberment": 600, "cheese_grater_of_peace": 400,
    "cloak_of_obscurity": 600, "dagger_of_treachery": 400, "eleven_foot_pole": 200,
    "flaming_armor": 400, "gentleman_s_club": 400, "hammer_of_kneecapping": 600,
    "helm_of_courage": 200, "horny_helmet": 600, "huge_rock": 0, "kneepads_of_allure": 600,
    "leather_armor": 200, "limburger_and_anchovy_sandwich": 400, "mace_of_sharpness": 600,
    "mithril_armor": 600, "pantyhose_of_giant_strength": 600, "pointy_hat_of_power": 400,
    "rapier_of_unfairness": 600, "rat_on_a_stick": 0, "sandals_of_protection": 700,
    "shield_of_ubiquity": 600, "short_wide_armor": 400, "singing_dancing_sword": 400,
    "slimy_armor": 200, "sneaky_bastard_sword": 400, "spiky_knees": 200, "staff_of_napalm": 800,
    "stepladder": 400, "swiss_army_polearm": 600, "tuba_of_charm": 300,
    "cotion_of_ponfusion": 100, "electric_radioactive_acid_potion": 200,
    "flaming_poison_potion": 100, "freezing_explosive_potion": 100, "magic_missile": 300,
    "nasty_tasting_sports_drink": 200, "potion_of_idiotic_bravery": 100,
    "pretty_balloons": 0, "sleep_potion": 100,
}


def set_identity(g, identity):
    if identity in {"male", "female"}:
        g.state.players[1].character_sex = identity
    elif identity and identity != "human":
        g.identity(identity)


def equipment_case(release, key):
    bonus, identity, incompatible, slot, big = EQUIPMENT[key]
    g = Game(release, level=9)
    set_identity(g, identity)
    cid = g.give(key)
    g.do(1, "carry_item", card_id=cid)
    assert combat_strength(g.state, 1, g.catalog) == 9
    g.do(1, "equip", card_id=cid)
    assert combat_strength(g.state, 1, g.catalog) == 9 + bonus
    g.open("net_troll")
    assert combat_totals(g.state, g.catalog) == (9 + bonus, 10)
    g.reject(1, "unequip", card_id=cid)
    if bonus > 0:
        if bonus == 1:
            # 9 + 1 is a losing ordinary tie; a real +2 potion enables victory.
            g.play("sleep_potion", target={"player_id": 1})
        g.safe_treasures()
        g.win()
        assert g.state.players[1].level == 10
        assert cid in g.state.players[1].in_play
        assert cid not in g.state.treasure_discard
    if incompatible:
        wrong = Game(release)
        set_identity(wrong, incompatible)
        bad = wrong.give(key)
        wrong.do(1, "carry_item", card_id=bad)
        wrong.reject(1, "equip", card_id=bad)
    other = Game(release)
    set_identity(other, identity)
    other.state.active_user_id = 2
    other.state.turn_number = 4
    other.equip(key)
    assert combat_strength(other.state, 1, other.catalog) == 3 + bonus
    # Ordinary capacity remains separate from usability and Big carrying size.
    if slot in {"head", "armor", "footwear"}:
        conflict = {"head": "helm_of_courage", "armor": "leather_armor",
                    "footwear": "boots_of_butt_kicking"}[slot]
        if conflict == key:
            conflict = {"head": "horny_helmet", "armor": "slimy_armor",
                        "footwear": "sandals_of_protection"}[slot]
        conflict_id = other.give(conflict)
        other.reject(1, "equip", card_id=conflict_id)
    if slot in {"hand", "two_hands"}:
        weapon = "sneaky_bastard_sword" if key != "sneaky_bastard_sword" else "buckler_of_swashing"
        weapon_id = other.give(weapon)
        if slot == "two_hands":
            other.reject(1, "equip", card_id=weapon_id)
        else:
            other.do(1, "equip", card_id=weapon_id)
            third = other.give("rat_on_a_stick" if key != "rat_on_a_stick" else "gentleman_s_club")
            other.reject(1, "equip", card_id=third)
    if big and identity != "dwarf":
        extra = other.give("huge_rock" if key != "huge_rock" else "tuba_of_charm")
        other.reject(1, "carry_item", card_id=extra)
    if key == "horny_helmet":
        elf = Game(release, level=9)
        identity_id = elf.identity("elf")
        elf.equip(key)
        assert combat_strength(elf.state, 1, elf.catalog) == 12
        elf.do(1, "discard_identity", card_id=identity_id)
        assert combat_strength(elf.state, 1, elf.catalog) == 10
    item_economy_case(release, key)
    equipment_distinctive(release, key)


def item_economy_case(release, key):
    # Portfolio totals derive solely from this literal oracle, never runtime prices.
    pool = ["sleep_potion", "potion_of_idiotic_bravery", "leather_armor",
            "slimy_armor", "magic_missile", "broad_sword", "cloak_of_obscurity"]
    pool = [k for k in pool if k != key]
    for total, succeeds in ((900, False), (1000, True)):
        remaining = total - PRICES[key]
        choices = next(combo for count in range(len(pool) + 1)
                       for combo in combinations(pool, count)
                       if sum(PRICES[k] for k in combo) == remaining)
        g = Game(release)
        ids = [g.give(k) for k in (key, *choices)]
        if succeeds:
            g.do(1, "sell", card_ids=ids)
            assert g.state.players[1].level == 4
            assert set(ids).issubset(g.state.treasure_discard)
        else:
            g.reject(1, "sell", card_ids=ids)
    g = Game(release)
    cid = g.give(key)
    g.do(1, "carry_item", card_id=cid)
    events = g.do(1, "offer_trade", partner_id=2, offered_ids=[cid], requested_ids=[],
                  expires_at=NOW + timedelta(minutes=2))
    trade_id = next(e.data["trade_id"] for e in events if "trade_id" in e.data)
    g.do(2, "accept_trade", trade_id=trade_id)
    assert cid in g.state.players[2].in_play
    assert cid not in g.state.players[1].in_play


def equipment_distinctive(release, key):
    if key in {"boots_of_running_really_fast", "tuba_of_charm"}:
        success_die, failure_die = (3, 2) if key == "boots_of_running_really_fast" else (2, 1)
        for equipped, die, expected_level in ((True, success_die, 3), (True, failure_die, 1), (False, success_die, 1)):
            game = Game(release)
            cid = game.give(key)
            game.do(1, "equip" if equipped else "carry_item", card_id=cid)
            game.safe_treasures()
            game.lose_to("gazebo", die=die)
            assert game.state.players[1].level == expected_level
            assert len(game.state.players[1].hand) == (1 if key == "tuba_of_charm" and equipped and die == success_die else 0)
    elif key == "rat_on_a_stick":
        for monster_key, enhancer, succeeds in (("amazon", "ancient", True),
                                                ("3_872_orcs", "baby", False),
                                                ("lame_goblin", "humongous", True),
                                                ("crabs", "humongous", False)):
            game = Game(release, level=1)
            rat = game.give(key)
            game.do(1, "carry_item", card_id=rat)
            monster = game.open(monster_key)
            game.play(enhancer, actor=2, target={"monster_id": monster})
            game.do(1, "begin_escape")
            args = {"ability_key": "rat_on_a_stick_escape", "cost_ids": [rat], "target": {"monster_id": monster}}
            if succeeds:
                game.do(1, "use_ability", **args)
                game.decline_windows()
                assert rat in game.state.treasure_discard and game.state.combat is None
            else:
                game.reject(1, "use_ability", **args)
    elif key == "sandals_of_protection":
        for equipped, from_door, expected in ((True, True, 3), (True, False, 2), (False, True, 2)):
            game = Game(release)
            item = game.give(key)
            game.do(1, "equip" if equipped else "carry_item", card_id=item)
            if from_door:
                game.open("curse_lose_a_level")
                game.decline_windows()
            else:
                curse(game, "curse_lose_a_level")
            assert game.state.players[1].level == expected
    elif key == "kneepads_of_allure":
        game = Game(release)
        game.equip(key)
        game.state.players[2].level = 4
        game.open("net_troll")
        game.reject(1, "force_help", helper_id=3)
        game.do(1, "force_help", helper_id=2)
        assert game.state.combat.fighter_ids == [1, 2]
        assert combat_totals(game.state, game.catalog) == (7, 10)
        gazebo = Game(release)
        gazebo.equip(key)
        gazebo.state.players[2].level = 4
        gazebo.open("gazebo")
        gazebo.reject(1, "force_help", helper_id=2)
    elif key in {"flaming_armor", "staff_of_napalm"}:
        for equipped in (False, True):
            game = Game(release)
            if key == "staff_of_napalm":
                game.identity("wizard")
            item = game.give(key)
            game.do(1, "equip" if equipped else "carry_item", card_id=item)
            game.open("large_angry_chicken")
            game.safe_treasures()
            game.win()
            assert game.state.players[1].level == (5 if equipped else 4)
    elif key in {"eleven_foot_pole", "swiss_army_polearm"}:
        game = Game(release, level=1)
        item = game.give(key)
        game.do(1, "carry_item", card_id=item)
        monster = game.open("pit_bull")
        game.do(1, "begin_escape")
        game.do(1, "monster_action", monster_id=monster, choices={"option": "distract", "card_ids": [item]})
        game.decline_windows()
        assert item in game.state.treasure_discard and game.state.players[1].level == 1


def boost_case(release, key):
    amount = BOOSTS[key]
    for carried in (False, True):
        for monsters in (False, True):
            g = Game(release, level=9 if monsters else 7)
            cid = g.give(key, 2)
            if carried:
                g.do(2, "carry_item", card_id=cid)
                assert combat_strength(g.state, 2, g.catalog) == (9 if monsters else 7)
                g.reject(2, "equip", card_id=cid)
            monster = g.open("gazebo")
            target = {"monster_id": monster} if monsters else {"player_id": 1}
            g.do(2, "play_card", card_id=cid, target=target,
                 choices={"side": "monsters" if monsters else "fighters"})
            assert combat_totals(g.state, g.catalog) == ((9, 8 + amount) if monsters else (7 + amount, 8))
            assert cid in g.state.combat.played_card_ids
            g.reject(2, "play_card", card_id=cid, target=target)
            if monsters:
                g.reject(1, "declare_win")
            else:
                g.safe_treasures()
                before = len(g.state.players[1].hand)
                events = g.win()
                assert len(g.state.players[1].hand) == before + 2
                assert g.state.players[1].level == 8
                assert cid in g.state.treasure_discard
                assert all(e.audience == "user:1" for e in events if e.name == "treasure.drawn")
    if key == "pretty_balloons":
        g = Game(release)
        cid = g.give(key)
        g.do(1, "carry_item", card_id=cid)
        g.reject(1, "sell", card_ids=[cid])
    item_economy_case(release, key)
    if key == "flaming_poison_potion":
        game = Game(release)
        game.open("large_angry_chicken")
        game.play(key, target={"player_id": 1})
        game.safe_treasures()
        game.win()
        assert game.state.players[1].level == 5


def level_case(release, key):
    for phase in ("turn.prepare", "combat.active", "combat.run_away"):
        g = Game(release)
        cid = g.give(key)
        if phase.startswith("combat"):
            g.open("net_troll")
            if phase == "combat.run_away":
                g.do(1, "begin_escape")
        command = g.command(1, "play_card", card_id=cid, target={"player_id": 2})
        g.state, _ = decide(g.state, command, g.catalog, g.rng)
        assert_zones(g.state, g.catalog)
        assert g.state.players[1].level == 3
        assert g.state.players[2].level == 4
        assert cid in g.state.treasure_discard
        before = deepcopy(g.state)
        replay, events = decide(g.state, command, g.catalog, g.rng)
        assert replay == before and not events
    g = Game(release)
    g.state.players[2].level = 9
    cid = g.give(key)
    g.reject(1, "play_card", card_id=cid, target={"player_id": 2})


def strong_thief(g):
    g.identity("thief")
    for key in ("dagger_of_treachery", "cloak_of_obscurity", "boots_of_butt_kicking",
                "leather_armor", "helm_of_courage", "spiky_knees"):
        g.equip(key)
    assert combat_strength(g.state, 1, g.catalog) == 21


def enhancer_case(release, key):
    enemy, treasures = ENHANCERS[key]
    g = Game(release, level=9)
    strong_thief(g)
    modifier = g.give(key, 2)
    monster = g.open("net_troll")
    g.reject(2, "play_card", card_id=modifier, target={"monster_id": "missing"})
    g.do(2, "play_card", card_id=modifier, target={"monster_id": monster})
    assert combat_totals(g.state, g.catalog) == (21, enemy)
    g.safe_treasures()
    before = len(g.state.players[1].hand)
    g.win()
    assert len(g.state.players[1].hand) == before + treasures
    assert g.state.players[1].level == 10
    assert monster in g.state.door_discard and modifier in g.state.door_discard

    # The enhancement belongs to its target, while the other monster keeps 8/2T.
    multiple = Game(release, level=9)
    strong_human(multiple)
    multiple.state.players[1].level = 7
    multiple.play("really_impressive_title")
    primary = multiple.open("net_troll")
    additional = multiple.give("gazebo", actor=2)
    multiple.play("wandering_monster", actor=2, choices={"monster_card_id": additional})
    multiple.play(key, actor=2, target={"monster_id": primary})
    # Gazebo prevents help even as a second monster. A real +5 is sufficient.
    multiple.play("magic_missile", target={"player_id": 1})
    if enemy == 20:
        multiple.play("sleep_potion", target={"player_id": 1})
    assert combat_totals(multiple.state, multiple.catalog)[1] == enemy + 8
    multiple.safe_treasures()
    before = len(multiple.state.players[1].hand)
    multiple.win()
    assert multiple.state.players[1].level == 9
    assert len(multiple.state.players[1].hand) == before + treasures + 2
    if key == "baby":
        floor = Game(release, level=3)
        plant = floor.open("potted_plant")
        floor.play(key, actor=2, target={"monster_id": plant})
        assert combat_totals(floor.state, floor.catalog) == (3, 1)
        floor.safe_treasures()
        floor.win()
        assert floor.state.players[1].level == 4
        assert len(floor.state.players[1].hand) == 1


def strong_human(g):
    for key in ("chainsaw_of_bloody_dismemberment", "bad_ass_bandana",
                "boots_of_butt_kicking", "leather_armor", "spiky_knees",
                "singing_dancing_sword"):
        g.equip(key)
    assert combat_strength(g.state, 1, g.catalog) == 21


def monster_case(release, key):
    enemy, treasures, levels = MONSTERS[key]
    g = Game(release, level=9)
    strong_human(g)
    if key != "ghoulfiends":
        g.state.players[1].level = 7
        g.play("really_impressive_title")
    if key == "tongue_demon":
        payment = g.give("magic_missile")
        g.do(1, "carry_item", card_id=payment)
    monster = g.open(key)
    if key == "tongue_demon":
        g.decline_windows()
        g.respond(1, card_ids=[payment])
    if key == "stoned_golem" and getattr(g.state, "pending_decision", None):
        g.respond(1, option="fight")
    expected_fighter = 9 if key == "ghoulfiends" else 15 if key == "insurance_salesman" else 22
    assert combat_totals(g.state, g.catalog) == (expected_fighter, enemy)
    if key == "gazebo":
        g.reject(1, "ask_help", helper_id=2, treasure_count=0, item_ids=[])
    g.safe_treasures()
    before = len(g.state.players[1].hand)
    g.win()
    g.decline_windows()
    assert g.state.players[1].level == (10 if key == "ghoulfiends" else 7 + levels)
    assert len(g.state.players[1].hand) == before + treasures
    assert monster in g.state.door_discard
    if key in MONSTER_IDENTITY_BONUSES:
        identity, modified = MONSTER_IDENTITY_BONUSES[key]
        conditional = Game(release, level=7)
        conditional.identity(identity)
        if key == "tongue_demon":
            payment = conditional.give("magic_missile")
            conditional.do(1, "carry_item", card_id=payment)
        conditional.open(key)
        if key == "tongue_demon":
            conditional.decline_windows()
            conditional.respond(1, card_ids=[payment])
        assert combat_totals(conditional.state, conditional.catalog)[1] == modified
    if key in BAD_LEVELS:
        for level, expected in ((7, BAD_LEVELS[key]), (1, 1)):
            loss = Game(release, level=level)
            if key == "tongue_demon":
                # No eligible Item is a legal no-effect precombat discard.
                pass
            loss.lose_to(key)
            assert loss.state.players[1].level == expected
    elif key in {"bullrog", "plutonium_dragon", "squidzilla", "stoned_golem",
                 "unspeakably_awful_indescribable_horror"}:
        loss = Game(release, level=7)
        kept = loss.identity("elf") if key != "squidzilla" else loss.identity("dwarf")
        item = loss.equip("helm_of_courage")
        hidden = loss.give("magic_missile")
        loss.lose_to(key)
        assert not loss.state.players[1].alive
        assert kept in loss.state.players[1].in_play
        assert {item, hidden}.issubset(loss.state.corpse[1])
    elif key == "3_872_orcs":
        for die in range(1, 7):
            loss = Game(release, level=7)
            loss.lose_to(key, bad_die=die)
            if die < 3:
                assert not loss.state.players[1].alive
            else:
                assert loss.state.players[1].alive
                assert loss.state.players[1].level == {3: 4, 4: 3, 5: 2, 6: 1}[die]
    elif key == "bigfoot":
        loss = Game(release, level=7)
        worn = loss.equip("helm_of_courage")
        spare = loss.give("horny_helmet")
        loss.do(1, "carry_item", card_id=spare)
        loss.lose_to(key)
        assert worn in loss.state.treasure_discard
        assert spare in loss.state.players[1].in_play
    elif key == "ghoulfiends":
        loss = Game(release, level=7)
        loss.state.players[2].level, loss.state.players[3].level = 4, 2
        loss.lose_to(key)
        assert loss.state.players[1].level == 2
        restricted = Game(release, level=7)
        restricted.identity("wizard")
        restricted.equip("staff_of_napalm")
        restricted.open(key)
        restricted.play("magic_missile", target={"player_id": 1})
        assert combat_totals(restricted.state, restricted.catalog) == (7, 8)
        restricted.reject(1, "declare_win")
    elif key == "pukachu":
        loss = Game(release, level=7)
        item = loss.equip("helm_of_courage")
        hidden = [loss.give("magic_missile"), loss.give("warrior")]
        loss.lose_to(key)
        assert not loss.state.players[1].hand
        assert item in loss.state.players[1].in_play
        assert hidden[0] in loss.state.treasure_discard
        assert hidden[1] in loss.state.door_discard
        naked = Game(release, level=7)
        naked.open(key)
        naked.safe_treasures()
        naked.win()
        assert naked.state.players[1].level == 9
    elif key == "potted_plant":
        elf = Game(release, level=3)
        elf.identity("elf")
        elf.open(key)
        elf.safe_treasures()
        elf.win()
        assert len(elf.state.players[1].hand) == 2
        assert elf.state.players[1].level == 4
    elif key == "gelatinous_octahedron":
        loss = Game(release, level=7)
        loss.identity("dwarf")
        bigs = [loss.give("huge_rock"), loss.give("tuba_of_charm")]
        small = loss.give("magic_missile")
        for cid in bigs + [small]:
            loss.do(1, "carry_item", card_id=cid)
        loss.lose_to(key)
        assert all(cid in loss.state.treasure_discard for cid in bigs)
        assert small in loss.state.players[1].in_play
    elif key == "shrieking_geek":
        loss = Game(release, level=7)
        role, race = loss.identity("warrior"), loss.identity("elf")
        loss.play("super_munchkin")
        loss.play("half_breed")
        item = loss.equip("rapier_of_unfairness")
        loss.lose_to(key)
        assert {role, race, "super_munchkin:1", "half_breed:1"}.issubset(loss.state.door_discard)
        assert not loss.state.players[1].equipped
        assert item in loss.state.players[1].in_play
    elif key == "insurance_salesman":
        loss = Game(release, level=7)
        large = loss.give("cloak_of_obscurity")
        small = loss.give("broad_sword")
        keep = loss.give("warrior")
        loss.lose_to(key)
        loss.reject(1, "respond_decision", decision_id=loss.state.pending_decision.id,
                    choices={"card_ids": [large]})
        loss.respond(1, card_ids=[large, small])
        assert {large, small}.issubset(loss.state.treasure_discard)
        assert keep in loss.state.players[1].hand
    elif key == "platycore":
        for option in ("discard_hand", "lose_levels"):
            loss = Game(release, level=7)
            hidden = loss.give("magic_missile")
            loss.lose_to(key)
            loss.respond(1, option=option)
            if option == "discard_hand":
                assert not loss.state.players[1].hand
                assert loss.state.players[1].level == 7
            else:
                assert hidden in loss.state.players[1].hand
                assert loss.state.players[1].level == 5


def curse(g, key, victim=1, actor=2):
    source = g.play(key, actor=actor, target={"player_id": victim})
    g.decline_windows()
    return source


def monster_distinctive(release, key):
    if key == "crabs":
        g = Game(release, level=1)
        g.identity("wizard")
        armor = g.equip("leather_armor")
        spare_armor = g.give("slimy_armor")
        g.do(1, "carry_item", card_id=spare_armor)
        worn = [g.equip(k) for k in ("pantyhose_of_giant_strength", "spiky_knees",
                                    "kneepads_of_allure", "boots_of_butt_kicking")]
        retained = [g.equip("helm_of_courage"), g.equip("buckler_of_swashing")]
        sandals = g.give("sandals_of_protection")
        ladder = g.give("stepladder")
        for cid in (sandals, ladder):
            g.do(1, "carry_item", card_id=cid)
        hand_armor = g.give("flaming_armor")
        g.lose_to(key, die=6)
        assert {armor, spare_armor, *worn}.issubset(g.state.treasure_discard)
        assert {*retained, sandals, ladder}.issubset(g.state.players[1].in_play)
        assert hand_armor in g.state.players[1].hand
    elif key == "net_troll":
        # Printed maximum-level recipients; agreed seat order is fallback policy.
        for levels, recipients in (((5, 7, 6, 7), (2, 4)), ((7, 7, 6, 7), (2, 4)), ((8, 7, 6, 7), ())):
            g = Game(release, count=4)
            for uid, level in enumerate(levels, 1):
                g.state.players[uid].level = level
            items = [g.give("magic_missile"), g.give("sleep_potion")]
            secret = g.give("pretty_balloons")
            for cid in items:
                g.do(1, "carry_item", card_id=cid)
            g.lose_to(key)
            for receiver, cid in zip(recipients, items):
                assert g.state.pending_decision.chooser_ids == [receiver]
                g.reject(1, "respond_decision", decision_id=g.state.pending_decision.id, choices={"card_ids": [cid]})
                g.respond(receiver, card_ids=[cid])
                assert cid in g.state.players[receiver].in_play
            assert secret in g.state.players[1].hand
            assert not g.state.players[3].in_play
    elif key == "leperchaun":
        for count, receivers in ((2, (2, 2)), (3, (2, 3))):
            g = Game(release, count=count, level=7)
            items = [g.give("magic_missile"), g.give("sleep_potion")]
            for cid in items:
                g.do(1, "carry_item", card_id=cid)
            g.lose_to(key)
            for receiver, cid in zip(receivers, items):
                assert g.state.pending_decision.chooser_ids == [receiver]
                g.respond(receiver, card_ids=[cid])
                assert cid in g.state.players[receiver].in_play
    elif key == "snails_on_speed":
        for die, count, expected_count in ((3, 4, 3), (2, 5, 2), (6, 3, 3), (1, 0, 0)):
            g = Game(release, level=7)
            cards = [g.give(k) for k in ("magic_missile", "warrior", "wizard", "elf", "cleric")[:count]]
            if cards and die != 2:
                g.do(1, "carry_item", card_id=cards[0])
            g.lose_to(key, die=6, bad_die=die)
            if expected_count:
                chosen = cards[:expected_count]
                if count > expected_count:
                    g.reject(1, "respond_decision", decision_id=g.state.pending_decision.id,
                             choices={"card_ids": chosen[:-1]})
                g.respond(1, card_ids=chosen)
                assert set(chosen).issubset(g.state.door_discard + g.state.treasure_discard)
            assert len(g.state.players[1].hand) + len(g.state.players[1].in_play) == count - expected_count
    elif key == "lawyers":
        g = Game(release, count=4, level=7)
        originals = [g.give(k) for k in ("magic_missile", "warrior", "elf", "wizard", "cleric")]
        g.lose_to(key)
        assert not g.state.players[1].hand
        assert all(len(g.state.players[uid].hand) == 1 for uid in (2, 3, 4))
        passed = {g.state.players[uid].hand[0] for uid in (2, 3, 4)}
        assert passed.issubset(originals)
        assert set(originals) - passed <= set(g.state.door_discard + g.state.treasure_discard)
    elif key == "hippogriff":
        for count, order in ((2, (2, 2, 2)), (3, (3, 2, 3)), (6, (6, 5, 4))):
            g = Game(release, count=count, level=7)
            items = [g.give(k) for k in ("magic_missile", "sleep_potion", "pretty_balloons")]
            keep = g.give("warrior")
            for cid in items:
                g.do(1, "carry_item", card_id=cid)
            g.lose_to(key)
            for actor, cid in zip(order, items):
                assert g.state.pending_decision.chooser_ids == [actor]
                g.respond(actor, card_ids=[cid])
                assert cid in g.state.players[actor].in_play + g.state.players[actor].hand
            assert g.state.players[1].hand == [keep]
    elif key == "king_tut":
        g = Game(release, level=7)
        race = g.identity("elf")
        item = g.equip("helm_of_courage")
        hidden = g.give("warrior")
        g.lose_to(key)
        assert g.state.players[1].level == 5
        assert item in g.state.treasure_discard and hidden in g.state.door_discard
        assert race in g.state.players[1].in_play
    elif key == "amazon":
        female = Game(release)
        female.state.players[1].character_sex = "female"
        female.safe_treasures()
        female.open(key)
        female.decline_windows()
        assert female.state.combat is None
        assert female.state.players[1].level == 3
        assert len(female.state.players[1].hand) == 1
        loss = Game(release, level=7)
        role = loss.identity("warrior")
        loss.lose_to(key)
        assert loss.state.players[1].level == 7
        assert role in loss.state.door_discard
    elif key == "floating_nose":
        g = Game(release)
        cheap = g.give("sleep_potion")
        valid = g.give("eleven_foot_pole")
        monster = g.open(key)
        g.reject(1, "monster_action", monster_id=monster, choices={"option": "bribe", "card_ids": [cheap]})
        g.do(1, "monster_action", monster_id=monster, choices={"option": "bribe", "card_ids": [valid]})
        assert valid in g.state.treasure_discard
        assert g.state.players[1].hand == [cheap]
        assert g.state.players[1].level == 3 and g.state.combat is None
    elif key == "stoned_golem":
        for halfling in (False, True):
            g = Game(release)
            if halfling:
                g.identity("halfling")
            monster = g.open(key)
            args = {"monster_id": monster, "choices": {"option": "ignore"}}
            if halfling:
                g.reject(1, "monster_action", **args)
            else:
                g.do(1, "monster_action", **args)
                assert g.state.combat is None and not g.state.players[1].hand
                assert g.state.players[1].level == 3
    elif key == "wannabe_vampire":
        g = Game(release)
        g.identity("cleric")
        g.safe_treasures()
        monster = g.open(key)
        if g.state.combat:
            g.do(1, "monster_action", monster_id=monster, choices={"option": "chase_away"})
        g.decline_windows()
        assert g.state.players[1].level == 3 and len(g.state.players[1].hand) == 3
    elif key == "unspeakably_awful_indescribable_horror":
        g = Game(release, level=7)
        wizard = g.identity("wizard")
        g.play("super_munchkin")
        warrior = g.identity("warrior")
        g.lose_to(key)
        assert g.state.players[1].alive and wizard in g.state.door_discard
        assert g.state.players[1].role_ids == [warrior]

    # Literal pursuit boundaries and even-success penalties are separate rules.
    if key in {"bullrog", "hippogriff", "plutonium_dragon", "squidzilla", "king_tut", "wight_brothers"}:
        safe_level = {"bullrog": 4, "hippogriff": 3, "plutonium_dragon": 5,
                      "squidzilla": 4, "king_tut": 3, "wight_brothers": 3}[key]
        g = Game(release, level=safe_level)
        g.lose_to(key, die=1)
        assert g.state.players[1].alive and g.state.players[1].level == safe_level
        assert not g.state.players[1].hand
    if key in {"king_tut", "wight_brothers", "mr_bones"}:
        g = Game(release, level=7)
        g.lose_to(key, die=6)
        assert g.state.players[1].level == (6 if key == "mr_bones" else 5)


def curse_case(release, key):
    if key in {"curse_duck_of_doom", "curse_lose_a_level"}:
        for start, expected in ((7, 5 if key == "curse_duck_of_doom" else 6), (1, 1)):
            g = Game(release, level=start)
            source = curse(g, key)
            assert g.state.players[1].level == expected
            assert g.state.players[2].level == start
            assert source in g.state.door_discard
        return
    slots = {
        "curse_lose_the_armor_you_are_wearing": ("leather_armor", "slimy_armor"),
        "curse_lose_the_footgear_you_are_wearing": ("boots_of_running_really_fast", "sandals_of_protection"),
        "curse_lose_the_headgear_you_are_wearing": ("helm_of_courage", "horny_helmet"),
    }
    if key in slots:
        for worn in (True, False):
            g = Game(release)
            first, second = slots[key]
            selected = g.equip(first) if worn else None
            spare = g.give(second)
            g.do(1, "carry_item", card_id=spare)
            source = curse(g, key)
            if worn:
                assert selected in g.state.treasure_discard
            assert spare in g.state.players[1].in_play
            assert source in g.state.door_discard
        return
    g = Game(release, level=7)
    if key in {"curse_lose_a_big_item", "curse_lose_a_small_item", "truly_obnoxious_curse"}:
        if key == "curse_lose_a_big_item":
            g.identity("dwarf")
            selected, spare = g.give("huge_rock"), g.give("tuba_of_charm")
            invalid = g.give("magic_missile")
        elif key == "truly_obnoxious_curse":
            selected, spare = g.give("staff_of_napalm"), g.give("pointy_hat_of_power")
            invalid = spare
        else:
            selected, spare = g.give("magic_missile"), g.give("helm_of_courage")
            invalid = g.give("huge_rock")
        for cid in {selected, spare, invalid}:
            g.do(1, "carry_item", card_id=cid)
        source = curse(g, key)
        assert selected in g.state.players[1].in_play  # loss waits for owner choice
        pending = g.state.pending_decision
        g.reject(2, "respond_decision", decision_id=pending.id, choices={"card_ids": [selected]})
        g.reject(1, "respond_decision", decision_id=pending.id, choices={"card_ids": [invalid]})
        g.respond(1, card_ids=[selected])
        assert selected in g.state.treasure_discard
        assert spare in g.state.players[1].in_play
        assert source in g.state.door_discard
        empty = Game(release)
        source = curse(empty, key)
        assert source in empty.state.door_discard
    elif key in {"curse_change_class", "curse_change_race"}:
        old, replacement, earlier = (("warrior", "wizard", "cleric") if key == "curse_change_class"
                                     else ("elf", "dwarf", "halfling"))
        old_id = g.identity(old)
        for identity in (earlier, replacement):
            cid = identity + ":1"
            g.state.door_deck.remove(cid)
            g.state.door_discard.append(cid)
        source = curse(g, key)
        identities = g.state.players[1].role_ids if key == "curse_change_class" else g.state.players[1].race_ids
        assert identities == [replacement + ":1"]
        assert old_id in g.state.door_discard
        assert earlier + ":1" in g.state.door_discard
        assert source in g.state.door_discard
        no_match = Game(release)
        old_id = no_match.identity(old)
        curse(no_match, key)
        assert old_id in no_match.state.door_discard
        assert not (no_match.state.players[1].role_ids if key == "curse_change_class" else no_match.state.players[1].race_ids)
        no_identity = Game(release)
        curse(no_identity, key)
        assert no_identity.state.players[1].level == 3
    elif key in {"curse_lose_your_class", "curse_lose_your_race"}:
        first, second, enabler = (("warrior", "wizard", "super_munchkin")
                                   if key == "curse_lose_your_class" else ("elf", "dwarf", "half_breed"))
        g.identity(first)
        g.play(enabler)
        g.identity(second)
        curse(g, key)
        assert {first + ":1", second + ":1", enabler + ":1"}.issubset(g.state.door_discard)
        assert not (g.state.players[1].role_ids if key == "curse_lose_your_class" else g.state.players[1].race_ids)
        empty = Game(release)
        curse(empty, key)
        assert empty.state.players[1].level == (2 if key == "curse_lose_your_class" else 3)
    elif key == "curse_change_sex":
        item = g.equip("gentleman_s_club")
        g.open("net_troll")
        curse(g, key)
        assert g.state.players[1].character_sex == "female"
        assert item not in g.state.players[1].equipped
        assert combat_totals(g.state, g.catalog) == (2, 10)
        assert g.state.players[1].next_combat_penalty == 0
    elif key == "curse_lose_two_cards":
        for count in (0, 1, 2):
            game = Game(release, count=2)
            given = [game.give(k) for k in ("warrior", "magic_missile")[:count]]
            curse(game, key)
            assert not game.state.players[1].hand
            assert set(game.state.players[2].hand) == set(given)
    elif key == "curse_malign_mirror":
        g.state.players[1].level = 3
        g.identity("thief")
        g.equip("dagger_of_treachery")
        g.equip("leather_armor")
        g.play("really_impressive_title")
        source = curse(g, key)
        g.open("net_troll")
        assert combat_totals(g.state, g.catalog) == (7, 10)
        assert source in g.state.players[1].in_play
    elif key == "curse_chicken_on_your_head":
        worn = g.equip("helm_of_courage")
        source = curse(g, key)
        assert source in g.state.players[1].in_play
        g.do(1, "unequip", card_id=worn)
        assert source in g.state.players[1].in_play
        g.do(1, "equip", card_id=worn)
        curse(g, "curse_lose_the_headgear_you_are_wearing")
        assert source in g.state.door_discard and worn in g.state.treasure_discard
    elif key == "curse_income_tax":
        chosen = g.give("broad_sword")
        pay = [g.give("leather_armor", 2), g.give("helm_of_courage", 2)]
        short = g.give("magic_missile", 3)
        curse(g, key)
        g.respond(1, card_ids=[chosen])
        g.respond(2, card_ids=pay)
        g.respond(3, card_ids=[short])
        assert {chosen, short, *pay}.issubset(g.state.treasure_discard)
        assert [g.state.players[i].level for i in (1, 2, 3)] == [7, 7, 6]


def special_level_case(release, key):
    g = Game(release)
    if key == "kill_the_hireling":
        hireling = g.play("hireling", actor=2)
        item = g.give("bow_with_ribbons", 2)
        g.do(2, "assign_hireling", hireling_id=hireling, card_id=item)
        g.play(key, target={"player_id": 2, "card_id": hireling})
        assert {hireling, item}.issubset(g.state.treasure_discard)
        assert g.state.players[1].level == 4 and g.state.players[2].level == 3
        capped = Game(release, level=9)
        hireling = capped.play("hireling", actor=2)
        cid = capped.give(key)
        capped.reject(1, "play_card", card_id=cid, target={"player_id": 2, "card_id": hireling})
    elif key == "steal_a_level":
        for victim_level, victim_after in ((4, 3), (1, 1)):
            game = Game(release)
            game.state.players[2].level = victim_level
            game.play(key, target={"player_id": 2})
            assert game.state.players[1].level == 4
            assert game.state.players[2].level == victim_after
        capped = Game(release, level=9)
        cid = capped.give(key)
        capped.reject(1, "play_card", card_id=cid, target={"player_id": 2})
    elif key == "whine_at_the_gm":
        g.state.players[2].level = 5
        g.play(key, target={"player_id": 1})
        assert g.state.players[1].level == 4
        for target_level, other_level in ((5, 3), (5, 5), (9, 10)):
            capped = Game(release)
            capped.state.players[1].level, capped.state.players[2].level = other_level, target_level
            cid = capped.give(key)
            capped.reject(1, "play_card", card_id=cid, target={"player_id": 2})
    elif key == "mutilate_the_bodies":
        cid = g.give(key)
        g.reject(1, "play_card", card_id=cid, target={"player_id": 2})
        g.lose_to("net_troll", die=6)
        g.do(1, "play_card", card_id=cid, target={"player_id": 2})
        assert g.state.players[2].level == 4


def character_case(release, key):
    g = Game(release)
    identity = g.identity(key)
    assert identity in g.state.players[1].in_play
    if key in {"warrior", "cleric"}:
        costs = [g.give(k) for k in ("magic_missile", "sleep_potion", "pretty_balloons", "cotion_of_ponfusion")]
        monster = "undead_horse" if key == "cleric" else "net_troll"
        g.open(monster)
        ability = "cleric_turn_undead" if key == "cleric" else "warrior_berserk"
        for index, cost in enumerate(costs[:3], 1):
            g.do(1, "use_ability", ability_key=ability, cost_ids=[cost], target={})
            assert combat_totals(g.state, g.catalog)[0] == 3 + index * (3 if key == "cleric" else 1)
            assert cost in g.state.treasure_discard
        g.reject(1, "use_ability", ability_key=ability, cost_ids=[costs[3]], target={})
        if key == "warrior":
            tie = Game(release, level=8)
            tie.identity("warrior")
            tie.open("gazebo")
            tie.win()
            assert tie.state.players[1].level == 9
            ordinary = Game(release, level=8)
            ordinary.open("gazebo")
            ordinary.reject(1, "declare_win")
        else:
            no_undead = Game(release)
            no_undead.identity("cleric")
            cost = no_undead.give("magic_missile")
            no_undead.open("ghoulfiends")
            no_undead.reject(1, "use_ability", ability_key=ability, cost_ids=[cost], target={})
    elif key == "dwarf":
        for big in ("huge_rock", "tuba_of_charm", "mithril_armor"):
            cid = g.give(big)
            g.do(1, "carry_item", card_id=cid)
        for card in ("magic_missile", "sleep_potion", "pretty_balloons", "cotion_of_ponfusion", "warrior", "wizard"):
            g.give(card)
        g.state.phase = "turn.charity"
        g.do(1, "end_turn")
        assert g.state.active_user_id == 2
        assert len(g.state.players[1].hand) == 6
    elif key == "halfling":
        first = g.give("cloak_of_obscurity")
        other = g.give("broad_sword")
        g.do(1, "sell", card_ids=[first, other])
        assert g.state.players[1].level == 4
        second = g.give("mace_of_sharpness")
        g.reject(1, "sell", card_ids=[second])
    elif key == "thief":
        for die, success in ((4, True), (3, False)):
            game = Game(release)
            game.identity(key)
            cost = game.give("sleep_potion")
            item = game.equip("helm_of_courage", 2)
            game.rng = Dice(die)
            game.do(1, "use_ability", ability_key="thief_steal", cost_ids=[cost], target={"player_id": 2, "card_id": item})
            assert cost in game.state.treasure_discard
            assert item in game.state.players[1 if success else 2].in_play
            assert game.state.players[1].level == (3 if success else 2)
    elif key == "elf":
        for die, expected in ((4, 7), (3, 4)):
            game = Game(release, level=7)
            game.identity("elf")
            game.lose_to("gazebo", die=die)
            assert game.state.players[1].level == expected
    elif key == "wizard":
        costs = [g.give(k) for k in ("magic_missile", "sleep_potion", "pretty_balloons", "cotion_of_ponfusion")]
        monster = g.open("net_troll")
        g.reject(1, "use_ability", ability_key="wizard_charm", cost_ids=costs[:3], target={"monster_id": monster})
        g.safe_treasures()
        g.do(1, "use_ability", ability_key="wizard_charm", cost_ids=costs, target={"monster_id": monster})
        g.decline_windows()
        assert g.state.players[1].level == 3
        assert len(g.state.players[1].hand) == 3
        assert all(cid in g.state.treasure_discard for cid in costs)


def special_case(release, key):
    g = Game(release)
    if key in {"half_breed", "super_munchkin"}:
        first, second, third = (("elf", "dwarf", "halfling") if key == "half_breed"
                                else ("wizard", "warrior", "cleric"))
        empty_source = g.give(key)
        g.reject(1, "play_card", card_id=empty_source, target={})
        g.identity(first)
        g.do(1, "play_card", card_id=empty_source, target={})
        if key == "half_breed":
            unusable = g.give("bad_ass_bandana")
            g.reject(1, "equip", card_id=unusable)
            g.open("squidzilla")
            assert combat_totals(g.state, g.catalog) == (3, 18)
        else:
            g.equip("mithril_armor")
            g.open("harpies")
            assert combat_totals(g.state, g.catalog) == (6, 4)
        # Separate legal turn proves the two-identity allowance and excess choice.
        dual = Game(release)
        first_id = dual.identity(first)
        dual.play(key)
        second_id = dual.identity(second)
        third_id = dual.give(third)
        dual.reject(1, "play_identity", card_id=third_id)
        dual.do(1, "discard_identity", card_id=key + ":1")
        dual.do(1, "resolve_identity_excess", card_ids=[first_id])
        ids = dual.state.players[1].race_ids if key == "half_breed" else dual.state.players[1].role_ids
        assert ids == [second_id]
    elif key == "cheat":
        g.equip("buckler_of_swashing")
        g.equip("sneaky_bastard_sword")
        bow = g.give("bow_with_ribbons")
        g.do(1, "carry_item", card_id=bow)
        g.play(key, target={"player_id": 1, "card_id": bow})
        g.do(1, "equip", card_id=bow)
        assert combat_strength(g.state, 1, g.catalog) == 11
        assert g.state.players[1].attachments == {"cheat:1": bow}
        curse(g, "curse_lose_a_small_item")
        g.respond(1, card_ids=[bow])
        assert bow in g.state.treasure_discard and "cheat:1" in g.state.door_discard
    elif key == "hireling":
        hireling = g.play(key)
        bow = g.give("bow_with_ribbons")
        g.do(1, "assign_hireling", hireling_id=hireling, card_id=bow)
        assert combat_strength(g.state, 1, g.catalog) == 8
        second = g.give("mace_of_sharpness")
        g.reject(1, "assign_hireling", hireling_id=hireling, card_id=second)
        g.reject(1, "sell", card_ids=[hireling])
        monster = g.open("net_troll")
        g.do(1, "begin_escape")
        g.do(1, "use_ability", ability_key="hireling_escape", cost_ids=[hireling], target={"monster_id": monster})
        g.decline_windows()
        assert {hireling, bow}.issubset(g.state.treasure_discard)
        assert g.state.players[1].level == 3
    elif key == "really_impressive_title":
        source = g.play(key)
        assert combat_strength(g.state, 1, g.catalog) == 6
        g.reject(1, "sell", card_ids=[source])
        curse(g, "curse_lose_a_small_item")
        assert source in g.state.players[1].in_play
        assert combat_strength(g.state, 1, g.catalog) == 6
    elif key == "divine_intervention":
        for player in (1, 2):
            g.identity("cleric", actor=player, copy=player)
            g.state.players[player].level = 9
        # Door loot is a private acquisition; Divine alone becomes public.
        g.state.phase = "turn.after_door"
        cid = "divine_intervention:1"
        g.state.door_deck.remove(cid)
        g.state.door_deck.append(cid)
        events = g.do(1, "loot_room")
        assert g.state.players[1].level == g.state.players[2].level == 10
        assert g.state.players[3].level == 3
        assert cid in g.state.door_discard
        assert g.state.phase == "game.finished"
        assert any(e.name == "game.won" for e in events)
    elif key == "hoard":
        # Solo fight gives a private Treasure; its acquisition triggers Hoard.
        g.state.players[1].level = 9
        g.open("gazebo")
        g.safe_treasures()
        cid = "hoard:1"
        g.state.treasure_deck.remove(cid)
        g.state.treasure_deck.append(cid)
        events = g.win()
        g.decline_windows()
        assert cid in g.state.treasure_discard
        assert len(g.state.players[1].hand) == 4  # 2 original - Hoard + 3 extra.
        assert all(e.audience == "user:1" for e in events if e.name in {"treasure.drawn", "card.drawn"})
    elif key == "help_me_out_here":
        g.state.players[1].level = 6
        borrowed = g.equip("chainsaw_of_bloody_dismemberment", actor=2)
        g.open("gazebo")
        g.play(key, target={"player_id": 2, "card_id": borrowed})
        assert borrowed in g.state.players[1].equipped
        assert combat_totals(g.state, g.catalog) == (9, 8)
        g.win()
        assert borrowed in g.state.players[1].in_play
    elif key == "out_to_lunch":
        g.open("net_troll")
        g.safe_treasures()
        g.play(key, actor=2)
        g.decline_windows()
        assert g.state.combat is None
        assert len(g.state.players[1].hand) == 2
        assert g.state.players[1].level == 3 and not g.state.players[2].hand
    elif key == "wandering_monster":
        g.state.players[1].level = 9
        strong_human(g)
        g.open("gazebo")
        additional = g.give("net_troll", actor=2)
        g.play(key, actor=2, choices={"monster_card_id": additional})
        assert combat_totals(g.state, g.catalog) == (21, 18)
        g.safe_treasures()
        g.win()
        assert len(g.state.players[1].hand) == 5
        assert {"gazebo:1", additional, key + ":1"}.issubset(g.state.door_discard)
    elif key == "mate":
        g.state.players[1].level = 9
        strong_human(g)
        monster = g.open("net_troll")
        g.play(key, actor=2, target={"monster_id": monster})
        assert combat_totals(g.state, g.catalog) == (21, 20)
        assert len(g.state.combat.monster_ids) == 2
        assert len(g.state.combat.virtual_monsters) == 1
        g.safe_treasures()
        g.win()
        assert len(g.state.players[1].hand) == 6
        assert {monster, key + ":1"}.issubset(g.state.door_discard)
    elif key == "illusion":
        g.state.players[1].level = 9
        monster = g.open("net_troll")
        g.play("ancient", actor=2, target={"monster_id": monster})
        replacement = g.give("potted_plant", actor=2)
        g.play(key, actor=2, target={"monster_id": monster}, choices={"replacement_card_id": replacement})
        assert combat_totals(g.state, g.catalog) == (9, 1)
        g.safe_treasures()
        g.win()
        assert len(g.state.players[1].hand) == 1


def character_distinctive(release, key):
    off_turn = Game(release)
    off_turn.state.turn_number = 4
    cid = off_turn.give(key, 2)
    off_turn.reject(2, "play_identity", card_id=cid)
    if key == "cleric":
        g = Game(release)
        g.identity(key)
        cost = g.give("magic_missile")
        resurrected = "warrior:1"
        g.state.door_deck.remove(resurrected)
        g.state.door_discard.append(resurrected)
        untouched = g.state.door_deck[-1]
        g.do(1, "open_door", resurrection_ids=[cost])
        assert resurrected in g.state.players[1].hand
        assert cost in g.state.treasure_discard
        assert g.state.door_deck[-1] == untouched
    elif key == "dwarf":
        g = Game(release)
        race = g.identity(key)
        first, second = g.give("huge_rock"), g.give("tuba_of_charm")
        g.do(1, "carry_item", card_id=first)
        g.do(1, "carry_item", card_id=second)
        g.do(1, "discard_identity", card_id=race)
        assert g.state.players[1].pending_big_excess == 1
        g.reject(1, "resolve_big_items", card_ids=[second])
        g.do(1, "resolve_big_items", card_ids=[second], recipient_id=2)
        assert second in g.state.players[2].in_play
        assert g.state.players[1].pending_big_excess == 0
        seven = Game(release)
        seven.identity(key)
        for card in ("magic_missile", "sleep_potion", "pretty_balloons", "cotion_of_ponfusion", "warrior", "wizard", "elf"):
            seven.give(card)
        seven.state.phase = "turn.charity"
        seven.reject(1, "end_turn")
    elif key == "thief":
        g = Game(release, level=9)
        g.identity(key, actor=3)
        costs = [g.give(k, actor=3) for k in ("sleep_potion", "pretty_balloons", "magic_missile")]
        g.open("net_troll")
        g.do(1, "ask_help", helper_id=2, treasure_count=0, item_ids=[])
        g.do(2, "accept_help")
        g.do(3, "use_ability", ability_key="thief_backstab", cost_ids=[costs[0]], target={"player_id": 1})
        assert combat_totals(g.state, g.catalog) == (16, 10)
        g.reject(3, "use_ability", ability_key="thief_backstab", cost_ids=[costs[1]], target={"player_id": 1})
        g.do(3, "use_ability", ability_key="thief_backstab", cost_ids=[costs[1]], target={"player_id": 2})
        assert combat_totals(g.state, g.catalog) == (14, 10)
        g.reject(3, "use_ability", ability_key="thief_backstab", cost_ids=[costs[2]], target={"player_id": 3})
    elif key in {"wizard", "halfling"}:
        g = Game(release)
        g.identity(key)
        costs = [g.give(k) for k in ("sleep_potion", "pretty_balloons", "magic_missile", "cotion_of_ponfusion")]
        monster = g.open("gazebo")
        g.do(1, "begin_escape")
        g.rng = Dice(2) if key == "wizard" else Dice(1, 5)
        g.do(1, "run_away", monster_id=monster)
        assert g.state.players[1].level == 3
        ability = "wizard_flight" if key == "wizard" else "halfling_escape_retry"
        count = 3 if key == "wizard" else 1
        for cost in costs[:count]:
            g.do(1, "use_ability", ability_key=ability, cost_ids=[cost], target={"monster_id": monster})
        g.reject(1, "use_ability", ability_key=ability, cost_ids=[costs[count]], target={"monster_id": monster})
        g.decline_windows()
        if g.state.combat:
            g.do(1, "resolve_escape", monster_id=monster, now=NOW + timedelta(minutes=10))
            g.decline_windows()
        assert g.state.players[1].level == 3
        assert set(costs[:count]).issubset(g.state.treasure_discard)
    elif key == "elf":
        for elf_level, after in ((7, 9), (9, 10)):
            g = Game(release, level=9)
            strong_human(g)
            g.state.players[1].level = 5
            g.identity("elf", actor=2)
            g.state.players[2].level = elf_level
            monster = g.open("net_troll")
            g.play("mate", actor=3, target={"monster_id": monster})
            g.do(1, "ask_help", helper_id=2, treasure_count=0, item_ids=[])
            g.do(2, "accept_help")
            g.safe_treasures()
            g.do(1, "declare_win")
            g.do(3, "pass_reaction")
            g.do(1, "close_reaction")
            g.decline_windows()
            assert g.state.players[1].level == 7
            assert g.state.players[2].level == after


def exceptional_item_case(release, key):
    g = Game(release)
    if key == "wand_of_dowsing":
        for selected in ("warrior:1", "magic_missile:1"):
            game = Game(release)
            pile = game.state.door_deck if selected == "warrior:1" else game.state.treasure_deck
            discard = game.state.door_discard if selected == "warrior:1" else game.state.treasure_discard
            pile.remove(selected)
            discard.append(selected)
            source = game.play(key, target={"card_id": selected})
            assert selected in game.state.players[1].hand
            assert source in game.state.treasure_discard
        item = g.give(key)
        g.do(1, "sell", card_ids=[item])
        assert g.state.players[1].level == 4
    elif key == "doppleganger":
        g.state.players[1].level = 5
        g.equip("boots_of_butt_kicking")
        g.open("net_troll")
        g.play(key, target={"player_id": 1})
        assert combat_totals(g.state, g.catalog) == (14, 10)
        g.reject(1, "ask_help", helper_id=2, treasure_count=0, item_ids=[])
        g.play("sleep_potion", target={"player_id": 1})
        assert combat_totals(g.state, g.catalog) == (18, 10)
        g.win()
    elif key in {"magic_lamp", "pollymorph_potion"}:
        monster = g.open("net_troll")
        g.safe_treasures()
        g.play(key, target={"monster_id": monster})
        g.decline_windows()
        assert g.state.combat is None
        assert len(g.state.players[1].hand) == 3
        assert g.state.players[1].level == 3
    elif key == "friendship_potion":
        g.open("net_troll")
        g.play(key)
        g.decline_windows()
        assert g.state.combat is None and not g.state.players[1].hand
        assert g.state.players[1].level == 3
        events = g.do(1, "loot_room")
        assert len(g.state.players[1].hand) == 1
        assert all(e.audience == "user:1" for e in events if e.name == "card.drawn")
    elif key == "potion_of_halitosis":
        g.open("floating_nose")
        g.safe_treasures()
        g.play(key, target={"monster_id": "floating_nose:1"})
        g.decline_windows()
        assert g.state.players[1].level == 4
        assert len(g.state.players[1].hand) == 3
        for side in ("player_id", "monster_id"):
            ordinary = Game(release, level=7)
            monster = ordinary.open("gazebo")
            ordinary.play(key, target={side: 1 if side == "player_id" else monster})
            assert combat_totals(ordinary.state, ordinary.catalog) == ((9, 8) if side == "player_id" else (7, 10))
    elif key == "yuppie_water":
        for elves, expected in ((0, 6), (1, 8), (2, 10)):
            game = Game(release)
            if elves:
                game.identity("elf")
            if elves == 2:
                game.identity("elf", actor=2, copy=2)
            game.open("net_troll")
            game.do(1, "ask_help", helper_id=2, treasure_count=0, item_ids=[])
            game.do(2, "accept_help")
            game.play(key, target={"player_id": 1})
            assert combat_totals(game.state, game.catalog) == (expected, 10)
    elif key == "transferral_potion":
        g.state.players[2].level = 9
        g.equip("chainsaw_of_bloody_dismemberment", actor=2)
        g.open("net_troll")
        g.play(key, target={"player_id": 2})
        assert g.state.active_user_id == 1 and g.state.combat.leader_id == 2
        assert g.state.combat.fighter_ids == [2]
        g.safe_treasures()
        g.do(2, "declare_win")
        g.do(1, "pass_reaction")
        g.do(3, "pass_reaction")
        g.do(2, "close_reaction")
        g.decline_windows()
        assert g.state.players[2].level == 10
        assert len(g.state.players[2].hand) == 3
        assert g.state.players[1].level == 3 and not g.state.players[1].hand
    elif key == "wishing_ring":
        ring = g.give(key, actor=3)
        g.do(3, "carry_item", card_id=ring)
        source = g.play("curse_lose_a_level", actor=2, target={"player_id": 1})
        assert g.state.players[1].level == 3
        pending = g.state.pending_decision
        g.do(3, "play_card", card_id=ring, target={"player_id": 1}, choices={"effect_id": pending.id})
        assert g.state.players[1].level == 3
        assert ring in g.state.treasure_discard and source in g.state.door_discard
    elif key in {"loaded_die", "invisibility_potion", "flask_of_glue"}:
        actor = 2 if key == "flask_of_glue" else 1
        source = g.give(key, actor)
        monster = g.open("gazebo")
        g.do(1, "begin_escape")
        g.rng = Dice(5, 1) if key == "flask_of_glue" else Dice(1)
        g.do(1, "run_away", monster_id=monster)
        assert g.state.players[1].level == 3
        attempt_id = g.state.combat.escape_roll_ids[(1, monster)]
        choices = {"roll_id": attempt_id, "result": 6} if key == "loaded_die" else {"attempt_id": attempt_id}
        if key == "loaded_die":
            for result in (0, 7, True):
                g.reject(1, "play_card", card_id=source, target={}, choices={**choices, "result": result})
        g.do(actor, "play_card", card_id=source, target={"player_id": 1} if key == "flask_of_glue" else {}, choices=choices)
        g.decline_windows()
        if g.state.combat:
            g.do(1, "resolve_escape", monster_id=monster, now=NOW + timedelta(minutes=10))
            g.decline_windows()
        assert g.state.players[1].level == (1 if key == "flask_of_glue" else 3)
        assert source in g.state.treasure_discard
    elif key == "instant_wall":
        source = g.give(key)
        monster = g.open("net_troll")
        g.do(1, "begin_escape")
        g.do(1, "play_card", card_id=source, target={}, choices={"player_ids": [1]})
        if getattr(g.state, "pending_decision", None):
            g.respond(1, option="accept")
        g.decline_windows()
        assert g.state.combat is None and g.state.players[1].level == 3
        assert source in g.state.treasure_discard and monster in g.state.door_discard


@pytest.mark.parametrize("rule_key", sorted(set(EQUIPMENT) | set(BOOSTS) | set(LEVELS) | set(ENHANCERS) | set(MONSTERS) | set(CURSES) | set(CHARACTERS) | set(SPECIAL_LEVELS) | set(SPECIALS) | set(EXCEPTIONAL_ITEMS)))
def test_classic_definition_behavior(release, rule_key):
    if rule_key in EQUIPMENT:
        equipment_case(release, rule_key)
    elif rule_key in BOOSTS:
        boost_case(release, rule_key)
    elif rule_key in LEVELS:
        level_case(release, rule_key)
    elif rule_key in ENHANCERS:
        enhancer_case(release, rule_key)
    elif rule_key in MONSTERS:
        monster_case(release, rule_key)
        monster_distinctive(release, rule_key)
    elif rule_key in CURSES:
        curse_case(release, rule_key)
    elif rule_key in CHARACTERS:
        character_case(release, rule_key)
        character_distinctive(release, rule_key)
    elif rule_key in SPECIAL_LEVELS:
        special_level_case(release, rule_key)
    elif rule_key in SPECIALS:
        special_case(release, rule_key)
    else:
        exceptional_item_case(release, rule_key)
