"""Source-backed exceptional combat operations."""

from copy import deepcopy
from .model import Event, RuleError
from . import combat

# These are literal source descriptor variants, never data-driven registration.
SPECS = {
    "add_monster_from_hand": [{"separate_escape_attempts": True}],
    "duplicate_monster": [{"copy_modifiers": True, "separate_rewards": True}],
    "replace_monster": [{"discard_modifiers": True, "replacement_zone": "hand"}],
    "baby_modifier": [
        {
            "strength": -5,
            "minimum_monster_level": 1,
            "treasures": -1,
            "minimum_treasures": 1,
        }
    ],
    "doppleganger": [{"duplicate_player_strength": True, "requires_solo": True}],
    "pollymorph_potion": [{"treasure": True, "levels": 0}],
    "potion_of_halitosis": [{"combat_bonus": 2, "auto_kill_rule": "floating_nose"}],
    "magic_lamp": [
        {
            "own_turn_only": True,
            "can_follow_failed_escape": True,
            "treasure_if_only_monster": True,
            "levels": 0,
        }
    ],
    "friendship_potion": [
        {"remove_all_monsters": True, "treasures": 0, "levels": 0, "may_loot": True}
    ],
    "discard_all_monsters_draw_treasures": [{"amount": 2, "recipient": "main_fighter"}],
    "transferral_potion": [{"other_player": True, "original_player_may_loot": True}],
    "yuppie_water": [{"race": "elf", "amount_per_elf": 2}],
}
CHOICES = {
    "potion_of_halitosis": {"side"},
    "add_monster_from_hand": {"monster_card_id"},
    "replace_monster": {"replacement_card_id"},
}


def handler(key):
    def apply(state, target, args, catalog, *, choices, rng):
        c = state.combat
        if not c:
            raise RuleError("no combat")
        actor = choices["actor_id"]
        mid = choices.get("monster_id")
        now = choices.get("_now")
        if key in {"add_monster_from_hand", "replace_monster"}:
            cid = choices.get(
                "monster_card_id"
                if key == "add_monster_from_hand"
                else "replacement_card_id"
            )
            if cid not in state.players[actor].hand or catalog[cid].kind != "monster":
                raise RuleError("owned hand monster required")
            if key == "replace_monster":
                c.monster_ids.remove(mid)
                if mid not in c.virtual_monsters:
                    c.retired_monster_ids.append(mid)
            state.players[actor].hand.remove(cid)
            c.monster_ids.append(cid)
            combat.reconcile_monsters(state, catalog)
            return combat.settle_mandatory_monsters(state, catalog, rng, now)
        elif key == "duplicate_monster":
            ref = "mate:" + choices["played_card_id"]
            if ref in c.virtual_monsters:
                raise RuleError("duplicate virtual monster")
            c.virtual_monsters[ref] = c.virtual_monsters.get(mid, mid)
            c.monster_ids.append(ref)
            c.enhancer_groups[ref] = c.enhancer_groups.setdefault(mid, mid)
            c.monster_modifiers[ref] = deepcopy(c.monster_modifiers.get(mid, []))
        elif key == "baby_modifier":
            combat.add_enhancer(
                state,
                mid,
                args["strength"],
                args["treasures"],
                card_id=choices["played_card_id"],
                minimum_monster_level=1,
                minimum_treasures=1,
            )
        elif key == "doppleganger":
            if c.helper_id is not None:
                raise RuleError("Doppleganger requires solo fighter")
            c.double_strength = True
        elif key == "yuppie_water":
            from .character import identities

            amount = 2 * sum(
                "elf" in identities(state.players[u], catalog, "race")
                for u in c.fighter_ids
            )
            uid = combat.leader_id(state)
            c.temporary_strength[uid] = c.temporary_strength.get(uid, 0) + amount
        elif key in {"pollymorph_potion", "magic_lamp", "potion_of_halitosis"}:
            if key == "potion_of_halitosis" and (
                mid is None
                or combat.monster_card(state, mid, catalog).rule_key != "floating_nose"
            ):
                if choices.get("side") == "monsters":
                    c.monster_strength_bonus += 2
                else:
                    uid = combat.leader_id(state)
                    c.temporary_strength[uid] = c.temporary_strength.get(uid, 0) + 2
            else:
                levels, treasures = combat.monster_rewards(state, mid, catalog)
                if key == "magic_lamp":
                    if actor != state.active_user_id:
                        raise RuleError("Lamp requires own turn")
                    treasures = treasures if len(c.monster_ids) == 1 else 0
                return combat.remove_foe(
                    state,
                    mid,
                    catalog,
                    rng,
                    outcome="kill" if key == "potion_of_halitosis" else "removal",
                    levels=levels if key == "potion_of_halitosis" else 0,
                    treasures=treasures,
                    now=now,
                )
        elif key in {"friendship_potion", "discard_all_monsters_draw_treasures"}:
            c.retired_monster_ids.extend(
                m for m in c.monster_ids if m not in c.virtual_monsters
            )
            c.monster_ids = []
            c.original_may_loot = key == "friendship_potion"
            if key == "discard_all_monsters_draw_treasures":
                c.pending_rewards.append(
                    dict(
                        monster_id=choices["played_card_id"],
                        beneficiary=combat.leader_id(state),
                        levels=0,
                        treasures=2,
                        kill=False,
                        outcome="avoidance",
                        helper_id=None,
                        helper_elf=False,
                    )
                )
            return combat.settle_combat(state, catalog, rng, success=True, now=now)
        elif key == "transferral_potion":
            if target in c.fighter_ids or not state.players[target].alive:
                raise RuleError("transfer requires other living player")
            c.leader_id = target
            c.fighter_ids = [target]
            c.helper_id = None
            c.forced_helper = False
            c.pending_help = None
            c.help_treasure_count = 0
            c.help_item_ids = []
            c.double_strength = False
            c.original_may_loot = True
        return state, []

    return apply


def register(registered, specials):
    from .character_rules import exact_variant

    specials.update(
        {k: registered(handler(k), exact_variant(v)) for k, v in SPECS.items()}
    )


SPECS["take_item_to_win"] = [{"may_discard_own_items_before": True}]
CHOICES["take_item_to_win"] = {"discard_ids"}
_base_handler = handler


def handler(key):
    if key != "take_item_to_win":
        return _base_handler(key)

    def apply(state, target, args, catalog, *, choices, rng):
        from .items import (
            is_item_card,
            remove_owned_card,
            reconcile_possessions,
            can_use,
            _check_slots,
        )
        from .character import discard_cards

        actor = choices["actor_id"]
        cid = choices["card_id"]
        c = state.combat
        if (
            not c
            or actor not in c.fighter_ids
            or actor == target
            or combat.declare_result(state, combat.leader_id(state), catalog).outcome
            != "must_run_away"
        ):
            raise RuleError("requires losing participant taking another Item")
        ids = choices.get("discard_ids", [])
        p = state.players[actor]
        if (
            not isinstance(ids, list)
            or any(not isinstance(i, str) for i in ids)
            or len(ids) != len(set(ids))
            or any(
                i not in p.hand + p.in_play or not is_item_card(catalog[i]) for i in ids
            )
        ):
            raise RuleError("invalid own Item discard")
        discard_cards(state, actor, ids, catalog)
        remove_owned_card(state.players[target], cid)
        reconcile_possessions(state, target, catalog)
        p.in_play.append(cid)
        if not can_use(p, cid, catalog):
            raise RuleError("taken Item cannot be used")
        if catalog[cid].kind == "one_shot":
            from .effects import apply_effects

            p.in_play.remove(cid)
            c.played_card_ids.append(cid)
            state, events = apply_effects(
                state,
                actor,
                catalog[cid].effects,
                catalog,
                choices={
                    "actor_id": actor,
                    "played_card_id": cid,
                    "_now": choices.get("_now"),
                },
                rng=rng,
            )
        else:
            _check_slots(p, cid, catalog)
            p.equipped.append(cid)
            events = []
        if (
            combat.declare_result(state, combat.leader_id(state), catalog).outcome
            != "provisional_win"
        ):
            raise RuleError("taken Item must turn loss into victory")
        return state, events

    return apply
