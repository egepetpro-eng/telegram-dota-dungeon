"""Load immutable presentation metadata alongside physical engine cards."""

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

from dota_dungeon.core.model import CardDef, Catalog

from .validation import canonical_digest, validate_release


@dataclass(frozen=True)
class CardPresentation:
    display_name_ru: str
    description_ru: str
    dota_entity_id: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class CatalogRelease:
    version: str
    digest: str
    catalog: Catalog
    presentations: dict[str, CardPresentation]


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_release(path: Path) -> CatalogRelease:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    manifest = json.loads(path.with_name("source-manifest.json").read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_object)
    validate_release(raw, manifest)
    catalog: Catalog = {}
    presentations = {}
    for card_id, key in raw["instances"].items():
        definition = raw["definitions"][key]
        presentation = definition["presentation"]
        mechanics = deepcopy(definition["mechanics"])
        # The existing equipment engine calls its feet slot ``footwear``.
        if mechanics.get("slots") == "feet":
            mechanics["slots"] = "footwear"
        catalog[card_id] = CardDef.from_dict({
            **mechanics, "id": card_id, "rule_key": key, "name": presentation["display_name_ru"],
        })
        presentations[card_id] = CardPresentation(
            presentation["display_name_ru"], presentation["description_ru"],
            presentation["dota_entity_id"], tuple(presentation["source_refs"]),
        )
    return CatalogRelease(raw["version"], canonical_digest(raw), catalog, presentations)
