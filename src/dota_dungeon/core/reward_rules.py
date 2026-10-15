"""Shared combat entitlement settlement with simultaneous optional draw choices."""

from copy import deepcopy
from .model import Event, RuleError
from .character import identities
from .decisions import offer


def begin_rewards(state, catalog, rng, now, success, selections=None):
    from .combat import leader_id, monster_rewards

    c = state.combat
    if c.reward_state:
        raise RuleError("rewards already settling")
    if success:
        for mid in c.monster_ids:
            levels, treasures = monster_rewards(state, mid, catalog)
            c.pending_rewards.append(
                dict(
                    monster_id=mid,
                    beneficiary=leader_id(state),
                    levels=levels,
                    treasures=treasures,
                    kill=True,
                    outcome="kill",
                    helper_id=c.helper_id,
                    helper_treasure_count=c.help_treasure_count,
                    helper_item_ids=c.help_item_ids.copy(),
                    helper_elf=bool(
                        c.helper_id
                        and "elf"
                        in identities(state.players[c.helper_id], catalog, "race")
                    ),
                )
            )
        c.retired_monster_ids.extend(
            m for m in c.monster_ids if m not in c.virtual_monsters
        )
        c.monster_ids = []
    earned = [
        e
        for e in c.pending_rewards
        if (success or e["beneficiary"] != leader_id(state))
        and state.players[e["beneficiary"]].alive
    ]
    batches = []
    for uid in dict.fromkeys(e["beneficiary"] for e in earned):
        entries = [e for e in earned if e["beneficiary"] == uid]
        batches.append(
            dict(
                owner=uid,
                remaining=sum(e["treasures"] for e in entries),
                face_up=any(e["helper_id"] is not None for e in entries),
                acquired=[],
                helper_id=(
                    c.helper_id
                    if uid == leader_id(state)
                    else next(
                        (e["helper_id"] for e in entries if e["helper_id"] is not None),
                        None,
                    )
                ),
                helper_count=max(
                    (e.get("helper_treasure_count", 0) for e in entries), default=0
                ),
            )
        )
    c.reward_state = {
        "batches": batches,
        "earned": earned,
        "success": success,
        "held": [],
    }
    return advance(state, catalog, rng, now, selections=selections)


def allocation(batch):
    helper = batch["helper_id"]
    count = batch["remaining"]
    needed = (
        max(0, batch["helper_count"] - len(batch["acquired"]))
        if helper is not None
        else 0
    )
    allocated = []
    if helper is not None:
        allocated.append((helper, min(count, needed)))
    allocated.append((batch["owner"], max(0, count - needed)))
    return allocated


def advance(state, catalog, rng, now, *, selections=None):
    events = []
    while state.combat.reward_state["batches"]:
        session = state.combat.reward_state
        batch = session["batches"][0]
        if batch["remaining"]:
            alloc = allocation(batch)
            eligible = [
                uid
                for uid, count in alloc
                if count > 0
                and state.players[uid].alive
                and batch["face_up"]
                and "cleric" in identities(state.players[uid], catalog, "role")
            ]
            if eligible and (
                selections is None or not set(eligible).issubset(selections)
            ):
                events.extend(
                    offer(state, "reward_draw", eligible, {"maximum": dict(alloc)}, now)
                )
                for uid, costs in (selections or {}).items():
                    if uid not in eligible:
                        raise RuleError(
                            "no resurrection entitlement for selected player"
                        )
                    state, ev = respond_reward(
                        state, uid, {"card_ids": costs}, catalog, rng, now
                    )
                    events.extend(ev)
                return state, events
            state, drawn = draw_batch(state, catalog, rng, selections or {})
            events.extend(drawn)
            selections = None
            if state.combat.reward_state["batches"][0]["remaining"]:
                continue
        session = state.combat.reward_state
        batch = session["batches"].pop(0)
        helper = batch["helper_id"]
        if helper is not None and state.players[helper].alive:
            for cid in batch["acquired"][: batch["helper_count"]]:
                state.players[batch["owner"]].hand.remove(cid)
                state.players[helper].hand.append(cid)
            helper_cards = set(batch["acquired"][: batch["helper_count"]])
            events = [
                (
                    Event(e.audience, e.name, {**e.data, "recipient_id": helper})
                    if e.name == "treasure.drawn"
                    and e.data.get("card_id") in helper_cards
                    else e
                )
                for e in events
            ]
    state, final = finish(state, catalog)
    return state, events + final


def resurrection_cost_ids(state, user_id):
    """Owned hand costs exclude draws already promised to another recipient."""
    reserved = set()
    if state.combat and state.combat.reward_state:
        for batch in state.combat.reward_state["batches"]:
            if batch["owner"] == user_id and batch["helper_id"] is not None:
                reserved.update(batch["acquired"][: batch["helper_count"]])
    return [cid for cid in state.players[user_id].hand if cid not in reserved]


def validate_reward_cost(state, user_id, costs):
    from .play import validate_cost

    validate_cost(state.players[user_id], {"zone": "hand", "count": len(costs)}, costs)
    if not set(costs) <= set(resurrection_cost_ids(state, user_id)):
        raise RuleError("resurrection cost belongs to another reward recipient")


def draw_batch(state, catalog, rng, selections):
    from .draw import draw_cards

    c = state.combat
    session = c.reward_state
    batch = session["batches"][0]
    count = batch["remaining"]
    alloc = allocation(batch)
    plan = {}
    offset = 0
    if not isinstance(selections, dict) or set(selections) - {u for u, n in alloc}:
        raise RuleError("invalid resurrection recipients")
    for uid, n in alloc:
        costs = selections.get(uid, [])
        validate_reward_cost(state, uid, costs)
        if len(costs) > n:
            raise RuleError("resurrection exceeds entitlement")
        for i, cid in enumerate(costs):
            plan[offset + i] = (uid, cid)
        offset += n
    spent = {cid for uid, cid in plan.values() if uid == batch["owner"]}
    batch["acquired"] = [cid for cid in batch["acquired"] if cid not in spent]
    batch["remaining"] = 0
    before = set(state.players[batch["owner"]].hand) - {
        cid for uid, cid in plan.values() if uid == batch["owner"]
    }
    state, events = draw_cards(
        state,
        batch["owner"],
        "treasure",
        count,
        batch["face_up"],
        catalog,
        rng,
        resurrection_plan=plan,
    )
    batch = state.combat.reward_state["batches"][0]
    batch["acquired"].extend(
        cid for cid in state.players[batch["owner"]].hand if cid not in before
    )
    return state, [
        Event(e.audience, "treasure.drawn", e.data) if e.name == "card.drawn" else e
        for e in events
    ]


def respond_reward(state, actor, choices, catalog, rng, now, *, expire=False):
    d = state.pending_decision
    if expire:
        for uid in d.chooser_ids:
            d.responses.setdefault(uid, {"card_ids": []})
    else:
        if set(choices) != {"card_ids"} or not isinstance(choices["card_ids"], list):
            raise RuleError("invalid resurrection choices")
        costs = choices["card_ids"]
        validate_reward_cost(state, actor, costs)
        if len(costs) > d.payload["maximum"][actor]:
            raise RuleError("resurrection exceeds entitlement")
        if sum(len(v["card_ids"]) for v in d.responses.values()) + len(costs) > len(
            state.treasure_discard
        ):
            raise RuleError("insufficient face-up discard")
        d.responses[actor] = deepcopy(choices)
    if not set(d.chooser_ids) <= set(d.responses):
        return state, []
    selections = {uid: v["card_ids"] for uid, v in d.responses.items()}
    state.pending_decision = None
    return advance(state, catalog, rng, now, selections=selections)


def finish(state, catalog):
    from .combat import _discard_combat_cards, leader_id
    from .items import remove_owned_card, reconcile_possessions

    c = state.combat
    session = c.reward_state
    from .help_contracts import reconcile_contracts
    events = reconcile_contracts(state)
    for uid in dict.fromkeys(e["beneficiary"] for e in session["earned"]):
        entries = [e for e in session["earned"] if e["beneficiary"] == uid]
        levels = sum(e["levels"] for e in entries)
        state.players[uid].level = min(10, state.players[uid].level + levels)
        events.append(
            Event(
                "group",
                "combat.won",
                {
                    "fighter_id": uid,
                    "levels": levels,
                    "monster_ids": [e["monster_id"] for e in entries],
                },
            )
        )
    for e in session["earned"]:
        if e["kill"] and e["helper_elf"] and state.players[e["helper_id"]].alive:
            p = state.players[e["helper_id"]]
            p.level = min(10, p.level + 1)
            events.append(
                Event("group", "elf.helper_levels", {"user_id": p.user_id, "levels": 1})
            )
    contracts = {
        (e["beneficiary"], e["helper_id"], cid)
        for e in session["earned"]
        if e["helper_id"] is not None
        for cid in e.get("helper_item_ids", [])
    }
    for owner, helper, cid in contracts:
        if not state.players[helper].alive:
            continue
        p = state.players[owner]
        if cid not in p.in_play:
            raise RuleError("promised item changed owner")
        remove_owned_card(p, cid)
        state.players[helper].in_play.append(cid)
        reconcile_possessions(state, owner, catalog)
        reconcile_possessions(state, helper, catalog)
    for uid in c.fighter_ids:
        reconcile_possessions(state, uid, catalog)
    for cid in session["held"]:
        state.resolving_card_ids.remove(cid)
        getattr(state, f"{catalog[cid].deck}_discard").append(cid)
    _discard_combat_cards(state)
    from .character import discard_cards

    for uid in c.fighter_ids:
        discard_cards(
            state,
            uid,
            [
                cid
                for cid in state.players[uid].in_play
                if catalog[cid].rule_key == "curse_malign_mirror"
            ],
            catalog,
        )
    winners = [
        uid
        for uid in state.order
        if state.players[uid].alive and state.players[uid].level >= 10
    ]
    state.phase = (
        "game.finished"
        if winners or state.phase == "game.finished"
        else ("turn.after_door" if c.original_may_loot else "turn.charity")
    )
    state.combat = None
    state.after_combat = True
    events.extend(Event("group", "game.won", {"user_id": uid}) for uid in winners)
    return state, events
