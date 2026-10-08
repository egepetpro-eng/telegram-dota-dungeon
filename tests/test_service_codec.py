"""State persistence must preserve actual command-relevant types and secrets."""
from copy import deepcopy
from datetime import datetime, timezone
from random import Random

import pytest

from dota_dungeon.core.model import CombatState, GameState, Player, Trade
from dota_dungeon.service.codec import decode_rng, decode_state, encode_rng, encode_state


def rich_state():
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    return GameState(
        "persisted", -100123, 11, "combat.active", 11, [11, 22],
        {11: Player(11, hand=["secret"], in_play=["axe"], equipped=["axe"], ready=True),
         22: Player(22, level=3, alive=False)},
        combat=CombatState(fighter_ids=[11, 22], helper_id=22,
                           monster_ids=["creep"], passes={22},
                           reaction_deadline=now, pending_help=(22, 1, ["axe"]),
                           escape_pending={(11, "creep")}, temporary_strength={11: 2}),
        trades={"offer": Trade("offer", 11, 22, ["axe"], [], now)},
        processed_requests={"once"}, corpse={22: ["loot"]},
        corpse_looted_by={22: {11}}, corpse_hand={22: {"loot"}},
    )


def test_character_choices_and_unresolved_escape_survive_restart():
    import json
    from dota_dungeon.core.engine import decide
    from dota_dungeon.core.model import CardDef, Command
    state = rich_state()
    state.phase = "combat.run_away"
    state.combat.fighter_ids = [11]
    state.combat.helper_id = None
    state.combat.pending_help = None
    state.combat.escape_rolls = {(11, "creep"): 6}
    state.combat.escape_uses = {(11, "creep", "wizard_flight"): 1}
    state.combat.escape_bonuses = {(11, "creep"): 1}
    state.combat.ability_uses = {(11, "thief_backstab", 22): 1}
    state.combat.charmed_monster_ids = ["charmed"]
    state.players[11].character_sex = "female"
    state.players[11].attachments = {"cheat": "axe"}
    state.players[11].hireling_items = {"hireling": "carried"}
    state.players[11].in_play = ["axe", "cheat", "hireling", "carried"]
    catalog = {key: CardDef(key, "door", "monster", key, bonus=1)
               for key in ("creep", "charmed")}
    catalog.update({key: CardDef(key, "treasure", "item", key)
                    for key in ("axe", "carried")})
    catalog.update({key: CardDef(key, "treasure", "special", key)
                    for key in ("cheat", "hireling")})
    state.card_decks.update({key: "door" for key in catalog})
    restored = decode_state(json.loads(json.dumps(encode_state(state))))
    assert restored == state
    result, _ = decide(restored, Command("persisted", 11, "finish-die", "resolve_escape",
                                      {"monster_id": "creep"}), catalog, Random(42))
    assert result.combat is None
    assert result.phase == "turn.charity"
    assert set(result.door_discard) == {"creep", "charmed"}
    assert result.players[11].attachments == {"cheat": "axe"}
    assert result.players[11].hireling_items == {"hireling": "carried"}


def test_pending_identity_and_big_item_selections_roundtrip_as_owned_choices():
    import json
    state = rich_state()
    state.players[11].pending_big_excess = 2
    state.players[11].pending_identity_excess = {"race": 1, "role": 1}
    restored = decode_state(json.loads(json.dumps(encode_state(state))))
    assert restored.players[11].pending_big_excess == 2
    assert restored.players[11].pending_identity_excess == {"race": 1, "role": 1}
    assert restored.players[22].pending_big_excess == 0
    assert not restored.players[22].pending_identity_excess


def test_combat_trade_and_death_survive_json_roundtrip():
    import json
    state = rich_state()
    restored = decode_state(json.loads(json.dumps(encode_state(state))))
    assert restored == state
    assert restored.players[11].hand == ["secret"]
    assert restored.combat.escape_pending == {(11, "creep")}
    assert restored.combat.pending_help == (22, 1, ["axe"])
    assert restored.combat.reaction_deadline.tzinfo == timezone.utc
    restored.players[11].hand.clear()
    assert state.players[11].hand == ["secret"]


@pytest.mark.parametrize("mutate", [
    lambda raw: raw.update(schema_version=999),
    lambda raw: raw["state"]["fields"].update(unknown_field=True),
    lambda raw: raw["state"]["fields"].update(host_id=True),
    lambda raw: raw["state"]["fields"].update(order=["not-an-id"]),
    lambda raw: raw["state"].update(type="NotAModel"),
])
def test_corrupt_or_untrusted_state_is_rejected(mutate):
    raw = deepcopy(encode_state(rich_state()))
    mutate(raw)
    with pytest.raises(ValueError):
        decode_state(raw)


def test_naive_deadline_cannot_be_saved():
    state = rich_state()
    state.combat.reaction_deadline = datetime(2026, 10, 8)
    with pytest.raises(ValueError, match="timezone"):
        encode_state(state)


def test_saved_rng_resumes_same_future_without_reseed():
    rng = Random(1234)
    rng.randrange(100)
    restored = decode_rng(encode_rng(rng))
    assert [restored.randrange(100000) for _ in range(8)] == [rng.randrange(100000) for _ in range(8)]


def test_unknown_rng_schema_is_rejected():
    with pytest.raises(ValueError):
        decode_rng({"schema_version": 99, "state": []})
