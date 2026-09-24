"""Validate a versioned set of physical card definitions."""

from .model import CardDef, Catalog


DECKS = {"door", "treasure"}
KINDS = {"monster", "curse", "role", "race", "modifier", "item", "one_shot", "level_up", "special"}
EFFECTS = {
    "gain_level", "lose_level", "add_strength", "remove_item", "persistent",
    "draw", "monster_modifier", "escape_modifier", "prevent_bad_stuff",
    "kill_monster", "remove_monster",
}


def load_catalog(raw: dict) -> Catalog:
    cards: Catalog = {}
    for entry in raw["cards"]:
        card_id = entry.get("id")
        if not isinstance(card_id, str) or not card_id:
            raise ValueError("missing card id")
        if card_id in cards:
            raise ValueError("duplicate card id")
        if entry.get("deck") not in DECKS:
            raise ValueError("invalid deck")
        if entry.get("kind") not in KINDS:
            raise ValueError("invalid kind")
        if not isinstance(entry.get("value", 0), int) or entry.get("value", 0) < 0:
            raise ValueError("negative value")
        for effect in entry.get("effects", []):
            if not isinstance(effect, dict) or effect.get("op") not in EFFECTS:
                raise ValueError("unknown effect")
        cards[card_id] = CardDef.from_dict(entry)
    return cards
