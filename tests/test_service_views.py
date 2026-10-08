from types import SimpleNamespace

import pytest

from dota_dungeon.core.model import CardDef, CombatState, GameState, Player


def fixture():
    catalog = {
        "secret-a": CardDef("secret-a", "treasure", "item", "Blink Dagger", value=500, bonus=2),
        "secret-b": CardDef("secret-b", "door", "curse", "Чужая тайная карта"),
        "visible-b": CardDef("visible-b", "treasure", "item", "Blade Mail", value=400, bonus=3, slots="armor"),
        "enemy": CardDef("enemy", "door", "monster", "Roshan", bonus=10, treasures=3),
    }
    release = SimpleNamespace(catalog=catalog, presentations={})
    state = GameState("g", -100, 11, "turn.prepare", 11, [11, 22], {
        11: Player(11, hand=["secret-a"], ready=True),
        22: Player(22, hand=["secret-b"], in_play=["visible-b"], equipped=["visible-b"], ready=True),
    })
    return state, release


def test_private_hand_and_buttons_never_include_other_players_hidden_cards():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    view = render_view(state, 11, "hand", release)
    assert view.destination == "user:11"
    assert "Blink Dagger" in view.text
    assert "Чужая тайная карта" not in view.text
    assert all(button.args.get("card_id") != "secret-b" for row in view.rows for button in row)


def test_public_profile_shows_visible_equipment_but_no_hand_cards():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    view = render_view(state, 11, "profile:22", release)
    assert "Blade Mail" in view.text
    assert "Чужая тайная карта" not in view.text
    assert "secret-b" not in str(view.rows)


def test_forged_private_card_selection_is_rejected():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    with pytest.raises(ValueError):
        render_view(state, 11, "card:secret-b", release)
    with pytest.raises(ValueError):
        render_view(state, 33, "hand", release)


def test_price_screen_includes_own_hand_and_visible_items_without_wallet():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    view = render_view(state, 11, "prices", release)
    assert "500" in view.text
    assert "стоимость вещей" in view.text.lower()
    assert "баланс" not in view.text.lower()
    assert "400" not in view.text


def test_group_combat_has_monster_and_strength_but_no_hidden_hand():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    state.phase = "combat.active"
    state.combat = CombatState(fighter_ids=[11], monster_ids=["enemy"])
    view = render_view(state, 11, "group", release)
    assert view.destination == "group"
    assert "Roshan" in view.text
    assert "10" in view.text
    assert "Blink Dagger" not in view.text
    assert "Чужая тайная карта" not in view.text


def test_player_supplied_name_is_html_escaped():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    view = render_view(state, 11, "profile:22", release, names={22: "<b>spoof</b>"})
    assert "&lt;b&gt;spoof&lt;/b&gt;" in view.text
    assert "<b>spoof</b>" not in view.text
