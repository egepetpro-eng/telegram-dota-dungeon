"""Shared acquisition chains, including mandatory source-verified triggers."""

from copy import deepcopy
from random import Random

from . import card_rules
from .model import CardDef, Catalog, Event, GameState, RuleError


class _DrawChain:
    def __init__(self, state: GameState, catalog: Catalog, rng: Random):
        self.state, self.catalog, self.rng = state, catalog, rng
        self.events: list[Event] = []
        self.processed: set[str] = set()
        self.held: list[tuple[int, str]] = []

    def trigger(
        self, user_id: int, card_id: str, face_up: bool, *, initial: bool = False
    ) -> None:
        card = self.catalog[card_id]
        descriptor = card.trigger
        if descriptor is None or card_id in self.processed:
            return
        if descriptor["timing"] == "initial_deal" and not initial:
            return
        rule = card_rules.TRIGGER_HANDLERS.get(descriptor["rule_key"])
        if rule is None:
            raise RuleError("unimplemented acquisition trigger")
        try:
            rule.validate_args(descriptor["args"])
        except ValueError as exc:
            raise RuleError(str(exc)) from exc
        self.processed.add(card_id)
        public = face_up or descriptor["visibility"] == "group"
        self.events.append(
            Event(
                "group" if public else f"user:{user_id}",
                "card.triggered",
                {
                    "card_id": card_id,
                    "recipient_id": user_id,
                    "rule_key": descriptor["rule_key"],
                },
            )
        )
        rule.handler(self, user_id, card_id, public, deepcopy(descriptor["args"]))

    def take(
        self,
        user_id: int,
        deck: str,
        count: int,
        face_up: bool,
        resurrection_ids=None,
        resurrection_owner_id=None,
        resurrection_plan=None,
    ) -> None:
        replacements = {}
        plan = resurrection_plan or {}
        if resurrection_ids:
            if plan:
                raise RuleError("duplicate resurrection selection forms")
            payer = user_id if resurrection_owner_id is None else resurrection_owner_id
            plan = {index: (payer, cid) for index, cid in enumerate(resurrection_ids)}
        if plan:
            from .character import identities, discard_cards
            from .play import validate_cost

            if not face_up:
                raise RuleError("resurrection requires face-up draw")
            by_owner = {}
            for index, choice in plan.items():
                if (
                    type(index) is not int
                    or not 0 <= index < count
                    or not isinstance(choice, tuple)
                    or len(choice) != 2
                ):
                    raise RuleError("invalid resurrection draw position")
                payer, cid = choice
                if type(payer) is not int or payer not in self.state.players:
                    raise RuleError("unknown resurrection payer")
                if "cleric" not in identities(
                    self.state.players[payer], self.catalog, "role"
                ):
                    raise RuleError("resurrection requires Cleric")
                by_owner.setdefault(payer, []).append(cid)
            for payer, costs in by_owner.items():
                validate_cost(
                    self.state.players[payer],
                    {"zone": "hand", "count": len(costs)},
                    costs,
                )
                if any(
                    (payer, cid) in self.state.pending_initial_triggers for cid in costs
                ):
                    raise RuleError("mandatory trigger card is reserved")
            discard = getattr(self.state, f"{deck}_discard")
            if len(discard) < len(plan):
                raise RuleError("insufficient matching face-up discard cards")
            # Simultaneous face-up choices cannot resurrect the costs just paid.
            replacements = {index: discard.pop() for index in sorted(plan)}
            for payer, costs in by_owner.items():
                discard_cards(self.state, payer, costs, self.catalog)
        for index in range(count):
            stack = getattr(self.state, f"{deck}_deck")
            discard = getattr(self.state, f"{deck}_discard")
            if index not in replacements and not stack and discard:
                stack.extend(discard)
                discard.clear()
                self.rng.shuffle(stack)
            if index not in replacements and not stack:
                self.events.append(
                    Event(
                        "group" if face_up else f"user:{user_id}",
                        "draw_unavailable",
                        {
                            "deck": deck,
                            "recipient_id": user_id,
                            "missing_count": count - index,
                        },
                    )
                )
                break
            card_id = replacements.pop(index) if index in replacements else stack.pop()
            card = self.catalog[card_id]
            self.state.players[user_id].hand.append(card_id)
            public = face_up or bool(
                card.trigger and card.trigger["visibility"] == "group"
            )
            self.events.append(
                Event(
                    "group" if public else f"user:{user_id}",
                    "card.drawn",
                    {"card_id": card_id, "recipient_id": user_id, "deck": deck},
                )
            )
            if self.state.phase == "lobby":
                if card.trigger:
                    self.state.pending_initial_triggers.append((user_id, card_id))
            else:
                self.trigger(user_id, card_id, face_up)

    def finish(self) -> None:
        for user_id, card_id in self.held:
            self.state.players[user_id].hand.remove(card_id)
            getattr(self.state, f"{self.catalog[card_id].deck}_discard").append(card_id)


def draw_cards(
    state: GameState,
    user_id: int,
    deck: str,
    count: int,
    face_up: bool,
    catalog: Catalog,
    rng: Random,
    *,
    resurrection_ids: list[str] | None = None,
    resurrection_owner_id: int | None = None,
    resurrection_plan: dict[int, tuple[int, str]] | None = None,
) -> tuple[GameState, list[Event]]:
    """Acquire up to count cards; exhausted piles preserve a partial acquisition."""
    if user_id not in state.players or deck not in {"door", "treasure"}:
        raise RuleError("invalid draw recipient or deck")
    if type(count) is not int or count < 0 or type(face_up) is not bool:
        raise RuleError("invalid draw count or visibility")
    transition_rng = deepcopy(rng)
    chain = _DrawChain(deepcopy(state), catalog, transition_rng)
    if resurrection_ids is not None and not isinstance(resurrection_ids, list):
        raise RuleError("invalid resurrection selections")
    if resurrection_plan is not None and not isinstance(resurrection_plan, dict):
        raise RuleError("invalid resurrection plan")
    chain.take(
        user_id,
        deck,
        count,
        face_up,
        resurrection_ids,
        resurrection_owner_id,
        resurrection_plan,
    )
    chain.finish()
    rng.setstate(transition_rng.getstate())
    return chain.state, chain.events


def resolve_initial_deal(state: GameState, catalog: Catalog, rng: Random):
    """All base hands exist before Hoard; Divine waits for identity choices."""
    chain = _DrawChain(deepcopy(state), catalog, rng)
    pending = chain.state.pending_initial_triggers.copy()
    chain.state.pending_initial_triggers.clear()
    for user_id, card_id in pending:
        if catalog[card_id].trigger["rule_key"] == "hoard":
            chain.trigger(user_id, card_id, False, initial=True)
        else:
            chain.state.pending_initial_triggers.append((user_id, card_id))
            chain.events.append(Event("group", "initial_trigger.pending", {
                "card_id": card_id, "recipient_id": user_id,
                "may_play_cleric_from_initial_hand": True,
                "resolves_before_first_door": True,
                "instruction": "All players may play a Cleric from their initial hand before this resolves at the first door."}))
    chain.finish()
    return chain.state, chain.events


def resolve_pending_initial_triggers(state: GameState, catalog: Catalog, rng: Random):
    chain = _DrawChain(deepcopy(state), catalog, rng)
    pending = chain.state.pending_initial_triggers.copy()
    chain.state.pending_initial_triggers.clear()
    for user_id, card_id in pending:
        if card_id in chain.state.players[user_id].hand:
            chain.trigger(user_id, card_id, True, initial=True)
    chain.finish()
    return chain.state, chain.events


def legacy_catalog(state: GameState) -> Catalog:
    """Old direct callers omit catalog; engine always supplies the real one."""
    return {cid: CardDef(cid, deck, "special", cid) for cid, deck in state.card_decks.items()}
