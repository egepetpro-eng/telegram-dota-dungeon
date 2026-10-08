"""Durable, private, actor-owned response stages and effect continuations."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from .model import PendingDecision, Event, RuleError


def time_value(now):
    return now if now is not None else datetime.now(timezone.utc)


def offer(state, kind, owners, payload, now=None):
    if state.pending_decision:
        raise RuleError("another decision is pending")
    state.decision_seq += 1
    d = PendingDecision(
        f"decision:{state.decision_seq}",
        kind,
        owners,
        time_value(now) + timedelta(seconds=30),
        payload,
    )
    state.pending_decision = d
    return [
        Event(
            "group",
            "decision.required",
            {
                "decision_id": d.id,
                "kind": kind,
                "chooser_ids": owners,
                "deadline": d.deadline.isoformat(),
                "mandatory": kind == "loss_choice",
            },
        )
    ]


def decision_options(state, user_id, catalog):
    d = state.pending_decision
    if not d:
        return None
    allowed = user_id in d.chooser_ids and user_id not in d.responses
    options = {}
    if allowed:
        if d.kind == "loss_choice":
            options = {
                k: deepcopy(d.payload.get(k))
                for k in ("card_ids", "count", "minimum_value", "options")
            }
            options["allow_decline"] = False
        elif d.kind == "reward_draw":
            options = {
                "card_ids": state.players[user_id].hand.copy(),
                "maximum": d.payload["maximum"].get(user_id, 0),
                "allow_decline": True,
            }
        elif d.kind == "wall_consent":
            options = {"options": ["accept", "decline"], "allow_decline": True}
        elif d.kind == "die_response":
            options = {"allow_decline": True, "roll_id": d.id, "die": d.payload["die"]}
        else:
            options = {"allow_decline": True}
    return dict(
        decision_id=d.id,
        kind=d.kind,
        deadline=d.deadline.isoformat(),
        mandatory=d.kind == "loss_choice",
        chooser_ids=d.chooser_ids.copy(),
        can_respond=allowed,
        choices=options,
    )


def selection(choices, payload):
    if payload.get("options"):
        if (
            payload.get("rule") == "treasure_choice"
            and set(choices) == {"card_ids"}
            and isinstance(choices["card_ids"], list)
            and len(choices["card_ids"]) == 1
            and choices["card_ids"][0] in payload["card_ids"]
        ):
            return choices["card_ids"][0]
        if set(choices) != {"option"} or choices["option"] not in payload["options"]:
            raise RuleError("invalid option")
        return choices["option"]
    ids = choices.get("card_ids")
    if (
        set(choices) != {"card_ids"}
        or not isinstance(ids, list)
        or any(not isinstance(i, str) for i in ids)
        or len(ids) != len(set(ids))
    ):
        raise RuleError("invalid card selections")
    if not set(ids) <= set(payload["card_ids"]):
        raise RuleError("ineligible selected card")
    if payload.get("count") is not None and len(ids) != payload["count"]:
        raise RuleError("wrong number of cards")
    return ids


def finish_source(state, cid, catalog):
    if cid in state.resolving_card_ids:
        state.resolving_card_ids.remove(cid)
        getattr(state, f"{catalog[cid].deck}_discard").append(cid)


def drain(state, catalog, rng, now):
    events = []
    while state.resolution_queue and not state.pending_decision:
        task = state.resolution_queue.pop(0)
        kind = task["kind"]
        if kind == "effects":
            from .effects import apply_effects

            state, ev = apply_effects(
                state,
                task["target"],
                task["effects"],
                catalog,
                choices={**task.get("context", {}), "_now": now},
                rng=rng,
            )
            events.extend(ev)
        elif kind == "source":
            finish_source(state, task["card_id"], catalog)
        elif kind == "loss":
            from .loss_rules import request_loss

            state, ev = request_loss(state, catalog, rng, now, **task["args"])
            events.extend(ev)
        elif kind == "escape_finish":
            from .combat import complete_escape

            state, ev = complete_escape(state, task["actor"], catalog, rng, now)
            events.extend(ev)
        else:
            raise RuleError("unknown continuation")
    return state, events


def respond_decision(
    state, actor, decision_id, choices, catalog, rng, now, *, expire=False
):
    d = state.pending_decision
    if not d or d.id != decision_id:
        raise RuleError("stale decision")
    if not isinstance(choices, dict):
        raise RuleError("choices must be object")
    if expire:
        if actor != state.active_user_id or now < d.deadline:
            raise RuleError("decision deadline not reached")
        if d.kind == "loss_choice":
            raise RuleError("mandatory victim choice cannot expire")
    elif actor not in d.chooser_ids or actor in d.responses:
        raise RuleError("not decision chooser")
    result = deepcopy(state)
    d = result.pending_decision
    events = []
    if d.kind == "loss_choice":
        picked = selection(choices, d.payload)
        from .loss_rules import fulfill_loss

        result, events = fulfill_loss(result, d.payload, picked, catalog, rng, now)
    elif d.kind == "curse_response":
        if choices:
            raise RuleError("curse continuation has no operands")
        result.pending_decision = None
        result.resolution_queue.insert(
            0,
            dict(
                kind="effects",
                target=d.payload["target_id"],
                effects=d.payload["effects"],
                context=d.payload["context"],
            ),
        )
    elif d.kind == "die_response":
        if choices:
            raise RuleError("die continuation has no operands")
        result.pending_decision = None
        from .loss_rules import settle_die

        result, events = settle_die(result, d.payload, catalog, rng, now)
    elif d.kind == "reward_draw":
        from .reward_rules import respond_reward

        return respond_reward(result, actor, choices, catalog, rng, now, expire=expire)
    elif d.kind == "wall_consent":
        from .response_rules import respond_wall

        result, events = respond_wall(
            result, actor, choices, catalog, rng, now, expire=expire
        )
    else:
        raise RuleError("unimplemented decision")
    result, ev = drain(result, catalog, rng, now)
    events.extend(ev)
    return result, events


def start_curse(state, actor, target, cid, catalog, now, *, door=False):
    from .items import remove_owned_card
    from .character import has_rule

    if door and any(
        catalog[i].rule_key == "sandals_of_protection"
        for i in state.players[target].equipped
    ):
        remove_owned_card(state.players[actor], cid)
        state.door_discard.append(cid)
        return state, [
            Event("group", "curse.immune", {"target_id": target, "card_id": cid})
        ]
    remove_owned_card(state.players[actor], cid)
    state.resolving_card_ids.append(cid)
    state.resolution_queue.append(dict(kind="source", card_id=cid))
    return state, offer(
        state,
        "curse_response",
        [target],
        dict(
            target_id=target,
            card_id=cid,
            effects=deepcopy(catalog[cid].effects),
            context={"actor_id": actor, "played_card_id": cid},
        ),
        now,
    )
