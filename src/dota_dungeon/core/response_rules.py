"""Cancellation, own dice and printed response cards."""

from .model import Event, RuleError
from .decisions import drain

SPECS = {
    "loaded_die": [
        {"result_min": 1, "result_max": 6, "own_roll_only": True, "after_roll": True}
    ],
    "cancel_curse": [{}],
    "wand_of_dowsing": [{}],
    "steal_a_level": [{"victim_loss": 1, "self_gain": 1, "can_win": False}],
}
CHOICES = {
    "loaded_die": {"roll_id", "result"},
    "cancel_curse": {"effect_id", "curse_id"},
}


def handler(key):
    def apply(state, target, args, catalog, *, choices, rng):
        actor = choices["actor_id"]
        now = choices.get("_now")
        if key == "loaded_die":
            value = choices.get("result")
            roll = choices.get("roll_id")
            if type(value) is not int or not 1 <= value <= 6:
                raise RuleError("die result must be integer 1..6")
            d = state.pending_decision
            if (
                d
                and d.kind == "die_response"
                and d.id == roll
                and d.payload["owner"] == actor
            ):
                d.payload["die"] = value
            elif state.combat:
                pair = next(
                    (
                        p
                        for p, rid in state.combat.escape_roll_ids.items()
                        if rid == roll
                        and p[0] == actor
                        and p in state.combat.escape_rolls
                    ),
                    None,
                )
                if pair is None:
                    raise RuleError("not own unresolved die")
                if pair in state.combat.automatic_escapes:
                    raise RuleError("automatic escape has no die")
                state.combat.escape_rolls[pair] = value
            else:
                raise RuleError("not own unresolved die")
        elif key == "cancel_curse":
            if set(choices) & {"effect_id", "curse_id"} == {"effect_id", "curse_id"}:
                raise RuleError("choose one curse target")
            d = state.pending_decision
            if "effect_id" in choices:
                if (
                    not d
                    or d.kind != "curse_response"
                    or d.id != choices["effect_id"]
                    or target != d.payload["target_id"]
                ):
                    raise RuleError("no matching pending curse")
                state.pending_decision = None
                return drain(state, catalog, rng, now)
            cid = choices.get("curse_id")
            if cid not in state.players[target].in_play or catalog[cid].kind != "curse":
                raise RuleError("not a continuing curse")
            from .character import discard_cards

            discard_cards(state, target, [cid], catalog)
        elif key == "wand_of_dowsing":
            cid = choices["card_id"]
            discard = getattr(state, f"{catalog[cid].deck}_discard")
            if cid not in discard:
                raise RuleError("card is not discarded")
            discard.remove(cid)
            state.players[actor].hand.append(cid)
            from .draw import _DrawChain

            chain = _DrawChain(state, catalog, rng)
            chain.trigger(actor, cid, False)
            chain.finish()
            return chain.state, [
                Event(
                    f"user:{actor}",
                    "card.drawn",
                    {"recipient_id": actor, "card_id": cid, "deck": catalog[cid].deck},
                ),
                *chain.events,
            ]
        elif key == "steal_a_level":
            if (
                target == actor
                or not state.players[target].alive
                or state.players[actor].level >= 9
            ):
                raise RuleError("invalid level theft")
            state.players[target].level = max(1, state.players[target].level - 1)
            state.players[actor].level += 1
        return state, []

    return apply


def register(registered, specials):
    from .character_rules import exact_variant

    specials.update(
        {k: registered(handler(k), exact_variant(v)) for k, v in SPECS.items()}
    )


SPECS.update(
    {
        "instant_wall": [{"maximum_players": 2, "before_roll": True}],
        "invisibility_potion": [{"after_failed_roll": True}],
        "flask_of_glue": [
            {
                "after_successful_escape": True,
                "reroll": True,
                "includes_automatic_escape": True,
            }
        ],
    }
)
CHOICES.update(
    {
        "instant_wall": {"player_ids"},
        "invisibility_potion": {"attempt_id"},
        "flask_of_glue": {"attempt_id"},
    }
)
_base_handler = handler


def handler(key):
    if key not in {"instant_wall", "invisibility_potion", "flask_of_glue"}:
        return _base_handler(key)

    def apply(state, target, args, catalog, *, choices, rng):
        from .combat import stamp_escape, escape_modifier, offer_automatic_escape
        from .decisions import offer

        actor = choices["actor_id"]
        now = choices.get("_now")
        c = state.combat
        if not c or state.phase != "combat.run_away":
            raise RuleError("escape response requires fleeing")
        if key == "instant_wall":
            ids = choices.get("player_ids")
            if (
                not isinstance(ids, list)
                or not 1 <= len(ids) <= 2
                or any(
                    type(u) is not int
                    or u not in c.fighter_ids
                    or not state.players[u].alive
                    for u in ids
                )
                or len(ids) != len(set(ids))
            ):
                raise RuleError("one or two fleeing players required")
            if any(pair[0] in ids for pair in c.escape_rolls):
                raise RuleError("Wall precedes rolls")
            if not all(any(pair[0] == uid for pair in c.escape_pending) for uid in ids):
                raise RuleError("player already left combat")
            others = [uid for uid in ids if uid != actor]
            payload = {
                "player_ids": ids,
                "actor_id": actor,
                "accepted": [actor] if actor in ids else [],
            }
            if others:
                return state, offer(state, "wall_consent", others, payload, now)
            return apply_wall(state, payload, catalog, rng, now)
        pair = next(
            (
                p
                for p, rid in c.escape_roll_ids.items()
                if rid == choices.get("attempt_id")
                and p in c.escape_rolls
                and p[0] == (actor if key == "invisibility_potion" else target)
            ),
            None,
        )
        if pair is None:
            raise RuleError("stale escape attempt")
        escaped = (
            pair in c.automatic_escapes
            or c.escape_rolls[pair] + escape_modifier(state, *pair, catalog) >= 5
        )
        if key == "invisibility_potion":
            if escaped:
                raise RuleError("Invisibility requires failed roll")
            return offer_automatic_escape(state, *pair, catalog, rng, now)
        if not escaped:
            raise RuleError("Glue requires successful escape")
        c.automatic_escapes.discard(pair)
        c.escape_rolls[pair] = rng.randint(1, 6)
        stamp_escape(state, pair, now)
        return state, [
            Event(
                "group",
                "escape.rerolled",
                {
                    "user_id": pair[0],
                    "monster_id": pair[1],
                    "die": c.escape_rolls[pair],
                },
            )
        ]

    return apply


def apply_wall(state, payload, catalog, rng, now):
    from .combat import offer_automatic_escape, escape_possible

    events = []
    for pair in sorted(state.combat.escape_pending):
        if pair[0] in payload["accepted"] and escape_possible(state, pair[1], catalog):
            state, ev = offer_automatic_escape(state, *pair, catalog, rng, now)
            events.extend(ev)
    return state, events


def respond_wall(state, actor, choices, catalog, rng, now, *, expire=False):
    d = state.pending_decision
    if expire:
        for uid in d.chooser_ids:
            d.responses.setdefault(uid, {"option": "decline"})
    else:
        if set(choices) != {"option"} or choices["option"] not in {"accept", "decline"}:
            raise RuleError("invalid willingness choice")
        d.responses[actor] = choices.copy()
    if not set(d.chooser_ids) <= set(d.responses):
        return state, []
    payload = d.payload
    payload["accepted"] += [
        uid for uid, v in d.responses.items() if v["option"] == "accept"
    ]
    state.pending_decision = None
    return apply_wall(state, payload, catalog, rng, now)
