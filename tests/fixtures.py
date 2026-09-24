from dota_dungeon.core.catalog import load_catalog


def small_catalog(doors=30, treasures=30):
    return load_catalog({"cards": [
        *({"id": f"d{i}", "deck": "door", "kind": "monster", "name": f"Creep {i}", "bonus": 1}
          for i in range(doors)),
        *({"id": f"t{i}", "deck": "treasure", "kind": "item", "name": f"Item {i}", "value": 100}
          for i in range(treasures)),
    ]})
