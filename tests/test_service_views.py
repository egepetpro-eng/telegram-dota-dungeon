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


def test_equipment_menu_hides_actions_that_core_rejects_in_combat():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    state.phase = "combat.active"
    state.combat = CombatState(fighter_ids=[11], monster_ids=["enemy"])
    state.players[11].in_play = ["secret-a"]
    view = render_view(state, 11, "equipment", release)
    assert not any(b.action in {"equip", "unequip"} for row in view.rows for b in row)


def test_sale_selection_is_immutable_and_confirms_only_legal_total():
    from dota_dungeon.telegram.views import render_selection
    state, release = fixture()
    state.players[11].hand.append("visible-b")
    release.catalog["visible-b"] = CardDef("visible-b", "treasure", "item", "Mail", value=500)
    empty = render_selection(state, 11, "sell", {}, release)
    choice = next(b for row in empty.rows for b in row if b.args.get("selected") == ["secret-a"])
    one = render_selection(state, 11, "sell", choice.args, release)
    assert not any(b.action == "sell" for row in one.rows for b in row)
    two = render_selection(state, 11, "sell", {"selected": ["secret-a", "visible-b"]}, release)
    assert next(b for row in two.rows for b in row if b.action == "sell").args == {"card_ids": ["secret-a", "visible-b"]}
    assert state.players[11].hand == ["secret-a", "visible-b"]
    assert any(b.action == "nav" for row in two.rows for b in row)
    with pytest.raises(ValueError):
        render_selection(state, 11, "sell", {"selected": ["secret-b"]}, release)


def test_trade_composition_exposes_only_open_items_and_both_sets():
    from dota_dungeon.telegram.views import render_selection
    state, release = fixture()
    state.players[11].in_play = ["secret-a"]
    state.players[11].hand = []
    view = render_selection(state, 11, "trade", {"partner_id": 22, "offered_ids": ["secret-a"], "requested_ids": ["visible-b"]}, release)
    offer = next(b for row in view.rows for b in row if b.action == "offer_trade")
    assert offer.args == {"partner_id": 22, "offered_ids": ["secret-a"], "requested_ids": ["visible-b"]}
    assert "Чужая тайная карта" not in view.text
    assert "secret-b" not in str(view.rows)


def test_charity_selector_chooses_excess_and_balances_lowest_players():
    from dota_dungeon.telegram.views import render_selection
    state, release = fixture()
    state.phase = "turn.charity"
    state.players[11].level = 3
    state.players[11].hand = [f"c{i}" for i in range(7)]
    for cid in state.players[11].hand:
        release.catalog[cid] = CardDef(cid, "door", "curse", cid)
    state.players[33] = Player(33)
    state.order.append(33)
    view = render_selection(state, 11, "charity", {"selected": ["c0", "c1"]}, release)
    button = next(b for row in view.rows for b in row if b.action == "give_charity")
    assert button.args == {"assignments": {22: ["c0"], 33: ["c1"]}}


def test_escape_and_corpse_controls_are_actor_scoped_and_hide_dead_hand():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    state.phase = "combat.run_away"
    state.combat = CombatState(fighter_ids=[11, 22], monster_ids=["enemy"], escape_pending={(11, "enemy"), (22, "enemy")})
    view = render_view(state, 11, "main", release)
    rolls = [b for row in view.rows for b in row if b.action == "run_away"]
    assert len(rolls) == 1 and rolls[0].actor_id == 11
    state.combat = None
    state.phase = "turn.charity"
    state.players[22].alive = False
    state.corpse = {22: ["visible-b", "secret-b"]}
    state.corpse_hand = {22: {"secret-b"}}
    state.corpse_looted_by = {22: set()}
    corpse = render_view(state, 11, "corpses", release)
    assert "Чужая тайная карта" not in corpse.text
    assert "secret-b" not in str(corpse.rows)


def test_card_menu_hides_unplayable_card_selector_and_trade_menu_hides_in_combat():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    state.phase = "lobby"
    state.active_user_id = None
    card = render_view(state, 11, "card:secret-a", release)
    assert not any(b.action == "choose_card_target" for row in card.rows for b in row)
    state.phase = "combat.active"
    state.combat = CombatState(fighter_ids=[11], monster_ids=["enemy"])
    trade = render_view(state, 11, "trade", release)
    assert not any(b.action == "trade_partner" for row in trade.rows for b in row)


@pytest.mark.parametrize("rule,target", [
    ("player", {"player_id": 22}), ("monster", {"monster_id": "enemy"}),
    ("open_item", {"player_id": 22, "card_id": "visible-b"}),
    ("identity", {"player_id": 22, "card_id": "role-b"}), ("discard", {"card_id": "discarded"}),
])
def test_play_selectors_resolve_closed_target_objects_without_hidden_cards(rule, target):
    from dota_dungeon.telegram.views import render_selection
    state, release = fixture()
    state.phase = "combat.active"
    state.combat = CombatState(fighter_ids=[11], monster_ids=["enemy"])
    state.players[22].in_play.append("role-b")
    release.catalog["role-b"] = CardDef("role-b", "door", "role", "Role")
    release.catalog["discarded"] = CardDef("discarded", "treasure", "item", "Discarded")
    state.treasure_discard = ["discarded"]
    release.catalog["secret-a"] = CardDef("secret-a", "treasure", "curse", "Play", effects=[{"op": "lose_level", "amount": 1}],
                                         play_phases=("combat.active",), target_rule=rule)
    view = render_selection(state, 11, "play", {"card_id": "secret-a"}, release)
    intentions = [b.args for row in view.rows for b in row if b.action == "play_card"]
    assert {"card_id": "secret-a", "target": target} in intentions
    assert "secret-b" not in str(view.rows)


def test_pending_initial_trigger_is_announced_without_revealing_initial_hand():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    state.pending_initial_triggers = ["secret-a"]
    view = render_view(state, 11, "group", release)
    assert "подготов" in view.text.lower()
    assert "перв" in view.text.lower()
    assert "Blink Dagger" not in view.text


def test_character_describes_identity_ability_cost_and_limits():
    from dota_dungeon.telegram.views import render_view
    state, release = fixture()
    state.players[11].role_ids = ["warrior"]
    state.players[11].in_play = ["warrior"]
    release.catalog["warrior"] = CardDef("warrior", "door", "role", "Warrior", abilities=[{
        "key": "warrior_berserk", "cost": {"zone": "hand", "count": 1},
        "limit": {"scope": "combat", "max_uses": 3}, "phases": ["combat.active"]}])
    view = render_view(state, 11, "character", release)
    assert "Стоимость" in view.text
    assert "3" in view.text and "1" in view.text
    assert "рук" in view.text.lower()


@pytest.mark.parametrize("phase, can_seek", [("turn.after_door", True), ("turn.prepare", False)])
def test_declared_monster_metadata_preserves_only_lawful_seek_trouble_controls(phase, can_seek):
    from random import Random
    from dota_dungeon.core.engine import decide
    from dota_dungeon.core.model import Command
    from dota_dungeon.telegram.views import render_selection, render_view
    state, release = fixture()
    state.phase = phase
    state.players[11].hand.append("enemy")
    release.catalog["enemy"] = CardDef("enemy", "door", "monster", "Roshan", bonus=2, treasures=1,
                                       levels=1, rule_key="fixture_monster", play_phases=("turn.after_door",), target_rule="self")
    detail = render_view(state, 11, "card:enemy", release)
    selection = render_selection(state, 11, "play", {"card_id": "enemy"}, release)
    selectors = [b for row in detail.rows for b in row if b.action == "choose_card_target"]
    plays = [b for row in selection.rows for b in row if b.action == "seek_trouble"]
    assert bool(selectors) is can_seek
    assert bool(plays) is can_seek
    if can_seek:
        assert plays[0].args == {"card_id": "enemy"} and plays[0].actor_id == 11
        result, _ = decide(state, Command("g", 11, "declared-monster", plays[0].action, plays[0].args), release.catalog, Random(0))
        assert result.phase == "combat.active"
        assert result.combat.monster_ids == ["enemy"]
        assert "enemy" not in result.players[11].hand
    assert "enemy" in state.players[11].hand
