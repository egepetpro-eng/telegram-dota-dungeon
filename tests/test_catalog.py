import pytest

from dota_dungeon.core.catalog import load_catalog


def test_catalog_rejects_duplicate_instance_ids():
    raw = {"cards": [
        {"id": "door-1", "deck": "door", "kind": "monster", "name": "Creep", "value": 0},
        {"id": "door-1", "deck": "door", "kind": "monster", "name": "Creep", "value": 0},
    ]}
    with pytest.raises(ValueError, match="duplicate card id"):
        load_catalog(raw)


@pytest.mark.parametrize("entry, error", [
    ({"id": "x", "deck": "unknown", "kind": "item", "name": "X", "value": 0}, "invalid deck"),
    ({"id": "x", "deck": "treasure", "kind": "item", "name": "X", "value": -1}, "negative value"),
    ({"deck": "door", "kind": "monster", "name": "X", "value": 0}, "missing card id"),
    ({"id": "x", "deck": "door", "kind": "bad", "name": "X", "value": 0}, "invalid kind"),
    ({"id": "x", "deck": "door", "kind": "curse", "name": "X", "value": 0,
      "effects": [{"op": "arbitrary_python"}]}, "unknown effect"),
])
def test_catalog_rejects_invalid_entries(entry, error):
    with pytest.raises(ValueError, match=error):
        load_catalog({"cards": [entry]})


def test_distinct_physical_copies_can_share_printed_name():
    raw = {"cards": [
        {"id": "a", "deck": "door", "kind": "monster", "name": "Creep", "value": 0},
        {"id": "b", "deck": "door", "kind": "monster", "name": "Creep", "value": 0},
    ]}
    assert list(load_catalog(raw)) == ["a", "b"]
