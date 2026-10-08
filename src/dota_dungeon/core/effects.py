"""Declarative effects resolved on an isolated state copy."""

from copy import deepcopy
from random import Random

from .model import Catalog, Event, GameState, RuleError


def _selected_card(state, target_id, effect, catalog, choices, rng):
    player = state.players[target_id]
    if 'card_id' in effect:
        cid = effect['card_id']
        if cid == choices.get('played_card_id') or cid not in player.hand + player.in_play:
            raise RuleError('card is not owned')
        return cid
    selector = effect['selector']
    source = player.hand if selector['zone'] == 'hand' else player.in_play
    eligible = [cid for cid in source if cid in catalog and cid != choices.get('played_card_id')]
    for key, attribute in (('kind', 'kind'), ('size', 'size'), ('slot', 'slots'), ('rule_key', 'rule_key')):
        if key in selector:
            value = 'footwear' if key == 'slot' and selector[key] == 'feet' else selector[key]
            eligible = [cid for cid in eligible if getattr(catalog[cid], attribute) == value]
    if 'slot' in selector:
        eligible = [cid for cid in eligible if cid in player.equipped]
    if 'tag' in selector:
        eligible = [cid for cid in eligible if selector['tag'] in catalog[cid].tags]
    if not eligible:
        raise RuleError('no eligible target card')
    selected = choices.get('card_id')
    if selected is not None:
        if selected not in eligible:
            raise RuleError('selected card is not eligible')
        # Callers cannot select another player hidden cards. Random loss is server-side.
        if selector['zone'] == 'hand' and choices.get('actor_id', target_id) != target_id:
            raise RuleError('cannot select another hidden hand')
        return selected
    return (rng or Random()).choice(eligible) if selector['zone'] == 'hand' else eligible[0]


def apply_effects(state: GameState, target_id: int, effects: list[dict],
                  catalog: Catalog, *, choices: dict | None = None,
                  rng: Random | None = None) -> tuple[GameState, list[Event]]:
    from dota_dungeon.cards.schema import validate_operation
    from .items import remove_owned_card, reconcile_equipment
    from .trade import cancel_trades_for_cards
    if target_id not in state.players:
        raise RuleError('unknown target')
    if choices is not None and not isinstance(choices, dict):
        raise RuleError('choices must be an object')
    choices = choices or {}
    for index, effect in enumerate(effects):
        if effect.get("op") in {"gain_level", "lose_level", "draw"}:
            amount = effect.get("amount", 1)
            if type(amount) is not int or amount <= 0:
                raise RuleError("effect requires positive amount")
        try:
            validate_operation(effect, f'effects[{index}]')
        except ValueError as exc:
            raise RuleError(str(exc)) from exc
    result = deepcopy(state)
    transition_rng = deepcopy(rng) if rng is not None else Random()
    events = []
    for effect in effects:
        player = result.players[target_id]
        op, amount = effect['op'], effect.get('amount', 1)
        if op == 'gain_level':
            if player.level + amount >= 10 and not effect.get('can_win', False):
                raise RuleError('effect cannot grant winning level')
            player.level = min(10, player.level + amount)
            if player.level == 10:
                result.phase = 'game.finished'
                events.append(Event('group', 'game.won', {'user_id': target_id}))
        elif op == 'lose_level':
            player.level = max(1, player.level - amount)
        elif op == 'add_strength':
            if result.combat:
                if target_id not in result.combat.fighter_ids:
                    raise RuleError('strength target is not a fighter')
                result.combat.temporary_strength[target_id] = result.combat.temporary_strength.get(target_id, 0) + amount
            else:
                player.strength_bonus += amount
        elif op == 'escape_modifier':
            player.escape_bonus += amount
        elif op == 'monster_modifier':
            if not result.combat:
                raise RuleError('no active combat')
            result.combat.monster_strength_bonus += amount
        elif op in {'prevent_bad_stuff', 'kill_monster', 'remove_monster'}:
            monster_id = effect['monster_id']
            if monster_id == "$target":
                monster_id = choices.get("monster_id")
            if not result.combat or monster_id not in result.combat.monster_ids:
                raise RuleError('unknown combat monster')
            if op == 'prevent_bad_stuff':
                if target_id not in result.combat.fighter_ids:
                    raise RuleError('target is not a fighter')
                result.combat.prevented_bad_stuff.add((target_id, monster_id))
            else:
                result.combat.monster_ids.remove(monster_id)
                result.door_discard.append(monster_id)
        elif op == 'remove_item':
            cid = _selected_card(result, target_id, effect, catalog, choices, transition_rng)
            hidden = cid in player.hand
            remove_owned_card(player, cid)
            deck = result.card_decks.get(cid, catalog[cid].deck if cid in catalog else 'treasure')
            (result.door_discard if deck == 'door' else result.treasure_discard).append(cid)
            cancel_trades_for_cards(result, [cid])
            reconcile_equipment(player, catalog)
            events.append(Event(f'user:{target_id}' if hidden else 'group', 'card.lost', {'target_id': target_id, 'card_id': cid}))
        elif op == 'draw':
            deck = effect.get('deck', 'treasure')
            stack = result.door_deck if deck == 'door' else result.treasure_deck
            discard = result.door_discard if deck == 'door' else result.treasure_discard
            if len(stack) + len(discard) < amount:
                raise RuleError('not enough cards to draw')
            drawn = []
            for _ in range(amount):
                if not stack:
                    stack.extend(discard)
                    discard.clear()
                    transition_rng.shuffle(stack)
                cid = stack.pop()
                player.hand.append(cid)
                drawn.append(cid)
            events.append(Event(f'user:{target_id}', 'card.drawn', {'count': amount, 'card_ids': drawn}))
        elif op == 'persistent':
            cid = effect.get('card_id', choices.get('played_card_id'))
            if cid not in catalog:
                raise RuleError('unknown persistent card')
            if cid not in player.in_play:
                source_player = result.players.get(choices.get('actor_id', target_id))
                if source_player and cid in source_player.hand:
                    source_player.hand.remove(cid)
                elif cid in result.door_discard:
                    result.door_discard.remove(cid)
                elif cid in result.treasure_discard:
                    result.treasure_discard.remove(cid)
                else:
                    raise RuleError('persistent card has no movable source')
                player.in_play.append(cid)
            if catalog[cid].kind == 'role' and cid not in player.role_ids:
                player.role_ids.append(cid)
            if catalog[cid].kind == 'race' and cid not in player.race_ids:
                player.race_ids.append(cid)
        elif op == 'special':
            from .card_rules import SPECIAL_HANDLERS
            registered = SPECIAL_HANDLERS[effect['rule_key']]
            result, special_events = registered.handler(result, target_id, deepcopy(effect['args']), catalog, choices=choices, rng=transition_rng)
            events.extend(special_events)
        events.append(Event('group', 'effect.applied', {'target_id': target_id, 'op': op}))
    if rng is not None:
        rng.setstate(transition_rng.getstate())
    return result, events
