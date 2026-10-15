"""Printed Bad Stuff selectors and victim-owned losses."""

from copy import deepcopy
from .model import Event, RuleError
from .character import discard_cards, identities, matches_identity
from .items import is_item_card, remove_owned_card, reconcile_possessions
from .decisions import offer


def owned_items(state, uid, catalog, *, public=False):
    p = state.players[uid]
    return [
        c
        for c in (p.in_play if public else p.hand + p.in_play)
        if is_item_card(catalog[c])
    ]


def request_loss(
    state,
    catalog,
    rng,
    now,
    *,
    victim,
    chooser=None,
    rule="discard",
    count=None,
    minimum_value=None,
    size=None,
    public=False,
    recipient=None,
    options=None,
    amount=None,
    card_ids=None,
):
    if recipient is not None and not state.players[recipient].alive:
        return state, []
    p = state.players[victim]
    eligible = (
        owned_items(state, victim, catalog, public=public)
        if card_ids is None
        else [cid for cid in card_ids if cid in p.hand + p.in_play]
    )
    if rule == "treasure_choice":
        eligible = [c for c in p.in_play if catalog[c].deck == "treasure"]
        options = eligible + (
            ["blind"] if any(catalog[c].deck == "treasure" for c in p.hand) else []
        )
        if not options:
            return state, []
        count = None
    if size:
        eligible = [cid for cid in eligible if catalog[cid].size == size]
    if (
        minimum_value is not None
        and sum(catalog[c].value for c in eligible) < minimum_value
    ):
        discard_cards(state, victim, eligible, catalog)
        if rule == "tax_payment":
            p.level = max(1, p.level - 1)
        return state, []
    if not eligible and not options:
        return state, []
    if count is not None:
        count = min(count, len(eligible))
    payload = dict(
        victim=victim,
        rule=rule,
        card_ids=eligible,
        count=count,
        minimum_value=minimum_value,
        options=options or [],
        recipient=recipient,
        amount=amount,
    )
    return state, offer(
        state, "loss_choice", [victim if chooser is None else chooser], payload, now
    )


def fulfill_loss(state, payload, picked, catalog, rng, now):
    victim = payload["victim"]
    p = state.players[victim]
    rule = payload["rule"]
    if (
        payload.get("recipient") is not None
        and not state.players[payload["recipient"]].alive
    ):
        raise RuleError("dead player cannot receive cards")
    if (
        payload.get("minimum_value") is not None
        and sum(catalog[c].value for c in picked) < payload["minimum_value"]
    ):
        raise RuleError("discarded Items do not meet required value")
    state.pending_decision = None
    events = []
    if rule == "lawyers":
        if len(picked) not in {0, 2}:
            raise RuleError("Lawyers exchange requires zero or two Treasures")
        discard_cards(state, victim, picked, catalog)
        if picked:
            from .draw import draw_cards

            state, events = draw_cards(
                state, victim, "treasure", 2, False, catalog, rng
            )
        from .combat import remove_foe

        state, ev = remove_foe(
            state, payload["monster_id"], catalog, rng, outcome="avoidance", now=now
        )
        return state, events + ev
    if rule == "treasure_choice":
        blind = picked == "blind"
        cid = (
            rng.choice([c for c in p.hand if catalog[c].deck == "treasure"])
            if blind
            else picked
        )
        remove_owned_card(p, cid)
        receiver = state.players[payload["recipient"]]
        (receiver.hand if blind else receiver.in_play).append(cid)
        reconcile_possessions(state, victim, catalog)
        reconcile_possessions(state, receiver.user_id, catalog)
        return state, [
            Event(
                f"user:{receiver.user_id}" if blind else "group",
                "card.received",
                {"card_id": cid, "recipient_id": receiver.user_id, "from_id": victim},
            )
        ]
    if payload["options"]:
        if picked == "discard_hand":
            discard_cards(state, victim, p.hand.copy(), catalog)
        elif picked == "lose_levels":
            p.level = max(1, p.level - payload["amount"])
        return state, events
    hidden = [c for c in picked if c in p.hand]
    if payload.get("recipient") is not None:
        receiver = state.players[payload["recipient"]]
        for cid in picked:
            remove_owned_card(p, cid)
            receiver.in_play.append(cid)
        reconcile_possessions(state, victim, catalog)
        reconcile_possessions(state, receiver.user_id, catalog)
    else:
        discard_cards(state, victim, picked, catalog)
    for cid in picked:
        events.append(
            Event(
                f"user:{victim}" if cid in hidden else "group",
                "card.lost",
                {"target_id": victim, "card_id": cid},
            )
        )
    if rule == "tax_base":
        value = sum(catalog[c].value for c in picked)
        state.resolution_queue[0:0] = [
            dict(
                kind="loss",
                args=dict(victim=uid, rule="tax_payment", minimum_value=value),
            )
            for uid in state.order
            if uid != victim and state.players[uid].alive
        ]
    return state, events


def die_opportunity(state, target, purpose, catalog, rng, now, **context):
    die = rng.randint(1, 6)
    events = offer(
        state,
        "die_response",
        [target],
        dict(owner=target, purpose=purpose, die=die, **context),
        now,
    )
    events.insert(
        0,
        Event(
            "group",
            "die.rolled",
            {
                "user_id": target,
                "purpose": purpose,
                "die": die,
                "roll_id": state.pending_decision.id,
            },
        ),
    )
    return state, events


def settle_die(state, payload, catalog, rng, now):
    uid = payload["owner"]
    die = payload["die"]
    purpose = payload["purpose"]
    if purpose == "orcs_bad_stuff_die":
        if die <= 2:
            return death(state, uid, catalog, rng)
        state.players[uid].level = max(1, state.players[uid].level - die)
    elif purpose == "discard_die_number_items_or_hand":
        p = state.players[uid]
        pool = list(
            dict.fromkeys(p.hand + owned_items(state, uid, catalog, public=True))
        )
        return request_loss(
            state, catalog, rng, now, victim=uid, count=die, card_ids=pool
        )
    elif purpose == "thief_theft":
        victim = payload["victim"]
        cid = payload["card_id"]
        if die >= 4:
            remove_owned_card(state.players[victim], cid)
            state.players[uid].in_play.append(cid)
            reconcile_possessions(state, victim, catalog)
            reconcile_possessions(state, uid, catalog)
        else:
            state.players[uid].level = max(1, state.players[uid].level - 1)
        from .trade import cancel_trades_for_cards

        cancel_trades_for_cards(state, [cid])
    return state, []


def death(state, uid, catalog, rng):
    p = state.players[uid]
    keep = set(
        p.role_ids
        + p.race_ids
        + [
            c
            for c in p.in_play
            if catalog[c].kind == "curse"
            or catalog[c].rule_key in {"half_breed", "super_munchkin"}
        ]
    )
    corpse = p.hand + [c for c in p.in_play if c not in keep]
    hand = set(p.hand)
    p.hand = []
    p.in_play = [c for c in p.in_play if c in keep]
    p.equipped = []
    p.attachments = {}
    p.hireling_items = {}
    p.alive = False
    p.rebirth_pending = True
    p.pending_big_excess = 0
    p.pending_identity_excess = {}
    state.corpse[uid] = corpse
    state.corpse_hand[uid] = hand
    state.corpse_looted_by[uid] = set()
    levels = sorted(
        {x.level for u, x in state.players.items() if u != uid and x.alive},
        reverse=True,
    )
    state.corpse_loot_order[uid] = [
        u
        for level in levels
        for u in dice_order(
            [
                u
                for u in state.order
                if u != uid
                and state.players[u].alive
                and state.players[u].level == level
            ],
            rng,
        )
    ]
    if state.combat:
        state.combat.escape_pending = {
            p for p in state.combat.escape_pending if p[0] != uid
        }
        state.combat.escape_rolls = {
            p: d for p, d in state.combat.escape_rolls.items() if p[0] != uid
        }
    from .trade import cancel_trades_for_cards

    cancel_trades_for_cards(state, corpse)
    return state, [
        Event(
            "group",
            "player.died",
            {"user_id": uid, "corpse_count": len(corpse), "card_ids": corpse.copy()},
        )
    ]


def neighbor(state, target, direction):
    i = state.order.index(target)
    return state.order[(i + (1 if direction == "left" else -1)) % len(state.order)]


def dice_order(ids, rng):
    if len(ids) < 2:
        return ids
    groups = {}
    for uid in ids:
        groups.setdefault(rng.randint(1, 6), []).append(uid)
    return [
        uid
        for die in sorted(groups, reverse=True)
        for uid in (
            dice_order(groups[die], rng) if len(groups[die]) > 1 else groups[die]
        )
    ]


def handler(key):
    def apply(state, target, args, catalog, *, choices, rng):
        p = state.players[target]
        now = choices.get("_now")
        events = []
        if not p.alive:
            return state, []
        if key in {"orcs_bad_stuff_die", "discard_die_number_items_or_hand"}:
            return die_opportunity(state, target, key, catalog, rng, now)
        if key == "death":
            return death(state, target, catalog, rng)
        if key == "death_except_discard_wizard":
            wizard = [cid for cid in p.role_ids if catalog[cid].rule_key == "wizard"]
            if wizard:
                discard_cards(state, target, wizard, catalog)
            else:
                return death(state, target, catalog, rng)
        elif key in {
            "set_level",
            "set_level_to_lowest_player",
            "lose_levels_race_variant",
        }:
            if key == "set_level":
                p.level = args["level"]
            elif key == "set_level_to_lowest_player":
                p.level = min(x.level for x in state.players.values())
            else:
                p.level = max(
                    1,
                    p.level
                    - (
                        args["race_amount"]
                        if matches_identity(
                            p, catalog, {"race_any": [args["race"]]}, disadvantage=True
                        )
                        else args["amount"]
                    ),
                )
        elif key in {
            "lose_class",
            "lose_race",
            "discard_all_identity",
            "lose_class_or_levels",
            "replace_identity_from_discard",
        }:
            kind = args.get("kind", "race" if key == "lose_race" else "role")
            ids = (
                (p.role_ids + p.race_ids).copy()
                if key == "discard_all_identity"
                else (p.race_ids if kind == "race" else p.role_ids).copy()
            )
            if not ids and key in {"lose_class", "lose_class_or_levels"}:
                p.level = max(
                    1,
                    p.level
                    - args.get("levels", args.get("if_no_class_lose_levels", 0)),
                )
            replacement = None
            if ids and key == "replace_identity_from_discard":
                replacement = next(
                    (
                        c
                        for c in reversed(state.door_discard)
                        if catalog[c].kind == kind
                    ),
                    None,
                )
            discard_cards(state, target, ids, catalog)
            if replacement:
                state.door_discard.remove(replacement)
                p.in_play.append(replacement)
                (p.race_ids if kind == "race" else p.role_ids).append(replacement)
                reconcile_possessions(state, target, catalog)
        elif key == "discard_hand":
            discard_cards(state, target, p.hand.copy(), catalog)
        elif key == "discard_all_items":
            discard_cards(
                state,
                target,
                [
                    c
                    for c in owned_items(state, target, catalog)
                    if not args.get("size") or catalog[c].size == args["size"]
                ],
                catalog,
            )
        elif key in {"discard_equipped", "discard_equipped_or_lose_level"}:
            slot = args["slot"]
            ids = [
                c
                for c in p.equipped
                if catalog[c].slots in {slot, "footwear" if slot == "feet" else slot}
            ]
            discard_cards(state, target, ids, catalog)
            if slot == "head":
                discard_cards(
                    state,
                    target,
                    [
                        c
                        for c in p.in_play
                        if catalog[c].rule_key == "curse_chicken_on_your_head"
                    ],
                    catalog,
                )
            if not ids and key == "discard_equipped_or_lose_level":
                p.level = max(1, p.level - args["amount"])
        elif key == "discard_armor_and_below_waist_items":
            below = {
                "boots_of_butt_kicking",
                "boots_of_running_really_fast",
                "sandals_of_protection",
                "pantyhose_of_giant_strength",
                "spiky_knees",
                "kneepads_of_allure",
            }
            discard_cards(
                state,
                target,
                [
                    c
                    for c in p.in_play
                    if catalog[c].slots == "armor"
                    or c in p.equipped
                    and catalog[c].rule_key in below
                ],
                catalog,
            )
        elif key in {"lose_item", "discard_chosen_item"}:
            return request_loss(
                state, catalog, rng, now, victim=target, count=1, size=args["size"]
            )
        elif key == "discard_items_value":
            return request_loss(
                state,
                catalog,
                rng,
                now,
                victim=target,
                minimum_value=args["minimum_value"],
            )
        elif key == "income_tax":
            return request_loss(
                state, catalog, rng, now, victim=target, count=1, rule="tax_base"
            )
        elif key == "choose_discard_hand_or_lose_levels":
            return request_loss(
                state,
                catalog,
                rng,
                now,
                victim=target,
                options=["discard_hand", "lose_levels"],
                amount=args["amount"],
            )
        elif key == "discard_largest_bonus_item":
            ids = owned_items(state, target, catalog)
            maximum = max((catalog[c].bonus for c in ids), default=0)
            return request_loss(
                state,
                catalog,
                rng,
                now,
                victim=target,
                count=1,
                card_ids=[c for c in ids if catalog[c].bonus == maximum],
            )
        elif key in {"items_chosen_by_neighbors", "items_to_highest_players"}:
            if key == "items_chosen_by_neighbors":
                receivers = [neighbor(state, target, d) for d in args["order"]]
            else:
                highest = max(x.level for x in state.players.values())
                receivers = dice_order(
                    [
                        u
                        for u in state.order
                        if u != target
                        and state.players[u].alive
                        and state.players[u].level == highest
                    ],
                    rng,
                )
            tasks = [
                dict(
                    kind="loss",
                    args=dict(
                        victim=target, chooser=uid, count=1, public=True, recipient=uid
                    ),
                )
                for uid in receivers
                if uid != target and state.players[uid].alive
            ]
            state.resolution_queue[0:0] = tasks
            from .decisions import drain

            return drain(state, catalog, rng, now)
        elif key in {
            "random_hand_cards_to_neighbors",
            "random_hand_to_other_players",
            "treasure_to_other_players",
        }:
            if key == "random_hand_cards_to_neighbors":
                receivers = [neighbor(state, target, d) for d in args["order"]]
            else:
                start = state.order.index(target)
                step = 1 if args["start"] == "left" else -1
                receivers = [
                    state.order[(start + step * i) % len(state.order)]
                    for i in range(1, len(state.order))
                ]
            if key == "treasure_to_other_players":
                receivers = [uid for uid in receivers if state.players[uid].alive]
                count = sum(
                    catalog[cid].deck == "treasure" for cid in p.hand + p.in_play
                )
                state.resolution_queue[0:0] = (
                    [
                        dict(
                            kind="loss",
                            args=dict(
                                victim=target,
                                chooser=receivers[i % len(receivers)],
                                rule="treasure_choice",
                                recipient=receivers[i % len(receivers)],
                            ),
                        )
                        for i in range(count)
                    ]
                    if receivers
                    else []
                )
                from .decisions import drain

                return drain(state, catalog, rng, now)
            for uid in receivers:
                if not state.players[uid].alive:
                    continue
                pool = p.hand.copy()
                if not pool:
                    continue
                cid = rng.choice(pool)
                remove_owned_card(p, cid)
                state.players[uid].hand.append(cid)
                events.append(
                    Event(
                        f"user:{uid}",
                        "card.received",
                        {"card_id": cid, "from_id": target},
                    )
                )
            if args.get("discard_remainder"):
                discard_cards(state, target, p.hand.copy(), catalog)
            from .decisions import drain

            state, ev = drain(state, catalog, rng, now)
            events.extend(ev)
        elif key in {"chicken_on_head", "malign_mirror"}:
            cid = choices["played_card_id"]
            if cid in state.resolving_card_ids:
                state.resolving_card_ids.remove(cid)
            else:
                for owner in state.players.values():
                    if cid in owner.hand:
                        owner.hand.remove(cid)
            p.in_play.append(cid)
        else:
            raise RuleError("unimplemented loss rule")
        return state, events

    return apply


def register(registered, specials):
    from .character_rules import exact_variant

    specials.update(
        {k: registered(handler(k), exact_variant(v)) for k, v in SPECS.items()}
    )


SPECS = {
    "chicken_on_head": [
        {"escape_penalty": -1, "remove_when": "curse_or_bad_stuff_removes_headgear"}
    ],
    "choose_discard_hand_or_lose_levels": [{"amount": 2}],
    "death": [{}],
    "death_except_discard_wizard": [{}],
    "discard_all_identity": [{"kinds": ["race", "role"]}],
    "discard_all_items": [{"size": "big"}, {}],
    "discard_armor_and_below_waist_items": [{}],
    "discard_chosen_item": [{"amount": 1, "size": "big"}],
    "discard_die_number_items_or_hand": [{}],
    "discard_equipped": [{"slot": "head"}, {"slot": "armor"}, {"slot": "feet"}],
    "discard_equipped_or_lose_level": [{"amount": 1, "slot": "feet"}],
    "discard_hand": [{}],
    "discard_items_value": [
        {"insufficient": "discard_all_items", "minimum_value": 1000}
    ],
    "discard_largest_bonus_item": [{}],
    "income_tax": [
        {
            "insufficient": "discard_all_items_and_lose_one_level",
            "others_payment": "items_at_least_discarded_item_value",
            "payer": "victim",
        }
    ],
    "items_chosen_by_neighbors": [{"items_each": 1, "order": ["left", "right"]}],
    "items_to_highest_players": [{"items_each": 1}],
    "lose_class": [{"discard_all": True, "if_no_class_lose_levels": 1}],
    "lose_class_or_levels": [{"levels": 3}],
    "lose_item": [{"choice": "victim", "size": "small"}],
    "lose_levels_race_variant": [{"amount": 2, "race": "elf", "race_amount": 3}],
    "lose_race": [{"discard_all": True}],
    "malign_mirror": [
        {"duration": "next_combat", "ignore_item_bonuses_except_slot": "armor"}
    ],
    "orcs_bad_stuff_die": [{"death_results": [1, 2], "lose_die_results": [3, 4, 5, 6]}],
    "random_hand_cards_to_neighbors": [{"cards_each": 1, "order": ["left", "right"]}],
    "random_hand_to_other_players": [
        {"cards_each": 1, "discard_remainder": True, "start": "left"}
    ],
    "replace_identity_from_discard": [
        {"kind": "role", "no_identity": "no_effect", "no_match": "discard_identity"},
        {"kind": "race", "no_identity": "no_effect", "no_match": "discard_identity"},
    ],
    "set_level": [{"level": 1}],
    "set_level_to_lowest_player": [{}],
    "treasure_to_other_players": [
        {
            "cards_each": 1,
            "hand_visibility": "blind",
            "start": "right",
            "zones": ["in_play", "hand"],
        }
    ],
}
