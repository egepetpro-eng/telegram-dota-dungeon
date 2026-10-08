"""Declarative effects resolved on an isolated state copy."""

from copy import deepcopy
from random import Random

from .model import Catalog, Event, GameState, RuleError


def _selected_card(state, target_id, effect, catalog, choices, rng):
    player = state.players[target_id]
    if "card_id" in effect:
        cid = effect["card_id"]
        if (
            cid == choices.get("played_card_id")
            or cid not in player.hand + player.in_play
        ):
            raise RuleError("card is not owned")
        return cid
    selector = effect["selector"]
    source = player.hand if selector["zone"] == "hand" else player.in_play
    eligible = [
        cid for cid in source if cid in catalog and cid != choices.get("played_card_id")
    ]
    for key, attribute in (
        ("kind", "kind"),
        ("size", "size"),
        ("slot", "slots"),
        ("rule_key", "rule_key"),
    ):
        if key in selector:
            value = (
                "footwear"
                if key == "slot" and selector[key] == "feet"
                else selector[key]
            )
            if key == "kind" and value == "item":
                from .items import is_item_card

                eligible = [cid for cid in eligible if is_item_card(catalog[cid])]
            else:
                eligible = [
                    cid for cid in eligible if getattr(catalog[cid], attribute) == value
                ]
    if "slot" in selector:
        eligible = [cid for cid in eligible if cid in player.equipped]
    if "tag" in selector:
        eligible = [cid for cid in eligible if selector["tag"] in catalog[cid].tags]
    if not eligible:
        raise RuleError("no eligible target card")
    selected = choices.get("card_id")
    if selected is not None:
        if selected not in eligible:
            raise RuleError("selected card is not eligible")
        # Callers cannot select another player hidden cards. Random loss is server-side.
        if (
            selector["zone"] == "hand"
            and choices.get("actor_id", target_id) != target_id
        ):
            raise RuleError("cannot select another hidden hand")
        return selected
    return (
        (rng or Random()).choice(eligible)
        if selector["zone"] == "hand"
        else eligible[0]
    )


def apply_effects(
    state: GameState,
    target_id: int,
    effects: list[dict],
    catalog: Catalog,
    *,
    choices: dict | None = None,
    rng: Random | None = None,
) -> tuple[GameState, list[Event]]:
    from dota_dungeon.cards.schema import validate_operation
    from .items import remove_owned_card, reconcile_possessions
    from .trade import cancel_trades_for_cards

    if target_id not in state.players:
        raise RuleError("unknown target")
    if choices is not None and not isinstance(choices, dict):
        raise RuleError("choices must be an object")
    choices = choices or {}
    for index, effect in enumerate(effects):
        if effect.get("op") in {"gain_level", "lose_level", "draw"}:
            amount = effect.get("amount", 1)
            if type(amount) is not int or amount <= 0:
                raise RuleError("effect requires positive amount")
        try:
            validate_operation(effect, f"effects[{index}]")
        except ValueError as exc:
            raise RuleError(str(exc)) from exc
    result = deepcopy(state)
    transition_rng = deepcopy(rng) if rng is not None else Random()
    events = []
    for effect_index, effect in enumerate(effects):
        player = result.players[target_id]
        op, amount = effect["op"], effect.get("amount", 1)
        if op == "gain_level":
            source = catalog.get(choices.get("played_card_id"))
            level_target = (
                choices["actor_id"]
                if source and source.rule_key == "kill_the_hireling"
                else target_id
            )
            player = result.players[level_target]
            if not player.alive:
                continue
            if player.level + amount >= 10 and not effect.get("can_win", False):
                raise RuleError("effect cannot grant winning level")
            player.level = min(10, player.level + amount)
            if player.level == 10:
                result.phase = "game.finished"
                events.append(Event("group", "game.won", {"user_id": level_target}))
        elif op == "lose_level":
            player.level = max(1, player.level - amount)
        elif op == "add_strength":
            if result.combat and choices.get("played_card_id"):
                result.combat.card_sides[choices["played_card_id"]] = choices.get(
                    "side", "fighters"
                )
            if result.combat and choices.get("side") == "monsters":
                result.combat.monster_strength_bonus += amount
            elif result.combat:
                from .combat import leader_id

                strength_target = choices.get("player_id", leader_id(result))
                if strength_target not in result.combat.fighter_ids:
                    raise RuleError("strength target is not a fighter")
                result.combat.temporary_strength[strength_target] = (
                    result.combat.temporary_strength.get(strength_target, 0) + amount
                )
            else:
                player.strength_bonus += amount
        elif op == "escape_modifier":
            player.escape_bonus += amount
        elif op == "monster_modifier":
            if not result.combat:
                raise RuleError("no active combat")
            if choices.get("monster_id"):
                from .combat import add_enhancer

                add_enhancer(
                    result,
                    choices["monster_id"],
                    amount,
                    effect.get("treasures", 0),
                    card_id=choices.get("played_card_id"),
                )
            else:
                result.combat.monster_strength_bonus += amount
        elif op in {"prevent_bad_stuff", "kill_monster", "remove_monster"}:
            monster_id = effect["monster_id"]
            if monster_id == "$target":
                monster_id = choices.get("monster_id")
            if not result.combat or monster_id not in result.combat.monster_ids:
                raise RuleError("unknown combat monster")
            if op == "prevent_bad_stuff":
                if target_id not in result.combat.fighter_ids:
                    raise RuleError("target is not a fighter")
                result.combat.prevented_bad_stuff.add((target_id, monster_id))
            else:
                from .combat import remove_foe, monster_rewards

                levels, treasures = monster_rewards(result, monster_id, catalog)
                result, outcome_events = remove_foe(
                    result,
                    monster_id,
                    catalog,
                    transition_rng,
                    outcome="kill" if op == "kill_monster" else "removal",
                    levels=levels if op == "kill_monster" else 0,
                    treasures=treasures if op == "kill_monster" else 0,
                    now=choices.get("_now"),
                )
                events.extend(outcome_events)
        elif op == "remove_item":
            cid = _selected_card(
                result, target_id, effect, catalog, choices, transition_rng
            )
            hidden = cid in player.hand
            remove_owned_card(player, cid)
            deck = result.card_decks.get(
                cid, catalog[cid].deck if cid in catalog else "treasure"
            )
            (result.door_discard if deck == "door" else result.treasure_discard).append(
                cid
            )
            cancel_trades_for_cards(result, [cid])
            reconcile_possessions(result, target_id, catalog)
            events.append(
                Event(
                    f"user:{target_id}" if hidden else "group",
                    "card.lost",
                    {"target_id": target_id, "card_id": cid},
                )
            )
        elif op == "draw":
            from .draw import draw_cards

            deck = effect.get("deck", "treasure")
            result, drawn_events = draw_cards(
                result, target_id, deck, amount, False, catalog, transition_rng
            )
            events.extend(drawn_events)
        elif op == "persistent":
            cid = effect.get("card_id", choices.get("played_card_id"))
            if cid not in catalog:
                raise RuleError("unknown persistent card")
            if cid not in player.in_play:
                source_player = result.players.get(choices.get("actor_id", target_id))
                if source_player and cid in source_player.hand:
                    source_player.hand.remove(cid)
                elif cid in result.resolving_card_ids:
                    result.resolving_card_ids.remove(cid)
                elif cid in result.door_discard:
                    result.door_discard.remove(cid)
                elif cid in result.treasure_discard:
                    result.treasure_discard.remove(cid)
                else:
                    raise RuleError("persistent card has no movable source")
                player.in_play.append(cid)
            if catalog[cid].kind == "role" and cid not in player.role_ids:
                player.role_ids.append(cid)
            if catalog[cid].kind == "race" and cid not in player.race_ids:
                player.race_ids.append(cid)
        elif op == "special":
            from .card_rules import SPECIAL_HANDLERS

            registered = SPECIAL_HANDLERS[effect["rule_key"]]
            result, special_events = registered.handler(
                result,
                target_id,
                deepcopy(effect["args"]),
                catalog,
                choices=choices,
                rng=transition_rng,
            )
            events.extend(special_events)
        events.append(
            Event("group", "effect.applied", {"target_id": target_id, "op": op})
        )
        if result.pending_decision:
            if effects[effect_index + 1 :]:
                result.resolution_queue.insert(
                    0,
                    dict(
                        kind="effects",
                        target=target_id,
                        effects=deepcopy(effects[effect_index + 1 :]),
                        context=deepcopy(choices),
                    ),
                )
            break
    if rng is not None and hasattr(rng, "setstate"):
        rng.setstate(transition_rng.getstate())
    return result, events
