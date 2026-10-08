from copy import deepcopy
from types import SimpleNamespace

import pytest

from dota_dungeon.cards.media import validate_media
from dota_dungeon.core.model import CardDef


def release():
    return SimpleNamespace(version="test", digest="a" * 64,
        catalog={"door:1": CardDef("door:1", "door", "monster", "Dota", rule_key="door")},
        presentations={"door:1": SimpleNamespace(dota_entity_id="hero:axe")})


def manifest():
    return {"media_version": "test-media-v1", "catalog_version": "test", "catalog_digest": "a" * 64,
            "assets": {"axe": {"dota_entity_id": "hero:axe", "image_url": "https://cdn.steamstatic.com/axe.png",
                "original_publication_url": "https://www.dota2.com/heroes", "credit": "Valve", "asset_kind": "portrait",
                "verified_on": "2026-10-08", "status": "verified", "notes": "inspected"}},
            "bindings": {"door": "axe"}}


def test_verified_matching_media_resolves_physical_copy():
    media = validate_media(manifest(), release())
    assert media.image_for("door:1") == "https://cdn.steamstatic.com/axe.png"
    assert media.image_for("unknown") is None


@pytest.mark.parametrize("change", ["draft", "digest", "foreign", "missing", "candidate", "unsafe", "unknown"])
def test_media_rejects_unpinned_incomplete_foreign_or_unverified_assets(change):
    raw = deepcopy(manifest())
    if change == "draft": raw["media_version"] += "-draft"
    if change == "digest": raw["catalog_digest"] = None
    if change == "foreign": raw["assets"]["axe"]["dota_entity_id"] = "hero:riki"
    if change == "missing": raw["bindings"] = {}
    if change == "candidate": raw["assets"]["axe"]["status"] = "candidate"
    if change == "unsafe": raw["assets"]["axe"]["image_url"] = "file:///secret"
    if change == "unknown": raw["bindings"]["extra"] = "axe"
    with pytest.raises(ValueError):
        validate_media(raw, release())
