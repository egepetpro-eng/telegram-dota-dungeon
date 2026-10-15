"""Conditional helper Item payments: reserved voluntarily, void on forced loss."""
from .model import Event, RuleError


def obligations(state):
    c = state.combat
    if c is None:
        return
    from .combat import leader_id
    owner = leader_id(state)
    if c.pending_help:
        helper, _, ids = c.pending_help
        yield owner, helper, ids
    if c.helper_id is not None:
        yield owner, c.helper_id, c.help_item_ids
    for entry in c.pending_rewards + c.reward_state.get('earned', []):
        if entry.get('helper_id') is not None:
            yield entry['beneficiary'], entry['helper_id'], entry.get('helper_item_ids', [])


def require_unpromised(state, owner, card_ids):
    reserved = {cid for uid, _, ids in obligations(state) if uid == owner for cid in ids}
    if reserved.intersection(card_ids):
        raise RuleError('promised Item cannot be spent voluntarily')


def reconcile_contracts(state):
    """Clear unavailable physical promises before continuations/reward settlement.

    The offered terms explicitly put forced-loss risk on the helper. Public Item
    IDs can be disclosed; no replacement or foreign hand is consulted.
    """
    lost = set()
    for owner, helper, ids in obligations(state):
        missing = [cid for cid in ids if cid not in state.players[owner].in_play]
        for cid in missing:
            ids.remove(cid)
            lost.add((owner, helper, cid))
    return [Event(audience, 'help.item_lost', {'owner_id': owner, 'helper_id': helper, 'card_id': cid})
            for owner, helper, cid in sorted(lost)
            for audience in ('group', f'user:{helper}')]
