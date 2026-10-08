"""Rendered character choices use accepted source definitions and the real engine."""
import json
from copy import deepcopy
from pathlib import Path
from random import Random
from types import SimpleNamespace
import pytest

from dota_dungeon.core.model import CardDef, CombatState, GameState, Player
from dota_dungeon.telegram.router import Router
from dota_dungeon.telegram.views import render_selection, render_view
from test_service_router import MemoryRepository, NOW, button, message, press


def fixture(role=None, race=None, phase="turn.prepare"):
    records = json.loads((Path(__file__).parents[1] / "src/dota_dungeon/cards/data/classic-dota-v1/source-manifest.json").read_text(encoding="utf-8"))["cards"]
    keys = {"warrior", "wizard", "cleric", "thief", "dwarf", "elf", "halfling", "half_breed", "super_munchkin", "hireling", "rat_on_a_stick", "cheat", "pretty_balloons", "bigfoot"}
    catalog = {r["rule_key"]: CardDef.from_dict({**r, "id": r["rule_key"], "name": r["rule_key"]}) for r in records if r["rule_key"] in keys}
    catalog.update({f"cost{i}": CardDef(f"cost{i}", "treasure", "item", f"Плата {i}", value=500) for i in range(8)})
    catalog["enemy"] = CardDef("enemy", "door", "monster", "Враг", bonus=4, treasures=2, bad_stuff=[{"op": "lose_level", "amount": 1}])
    catalog["secret"] = CardDef("secret", "door", "curse", "Чужая тайна")
    release = SimpleNamespace(catalog=catalog, presentations={}, version="accepted-character-test", digest="a" * 64)
    p = Player(11, level=4, hand=["cost0", "cost1", "cost2", "cost3"])
    for cid, ids in ((role, p.role_ids), (race, p.race_ids)):
        if cid:
            ids.append(cid)
            p.in_play.append(cid)
    state = GameState("g", -100, 11, phase, 11, [11, 22], {11: p, 22: Player(22, hand=["secret"])}, door_deck=["enemy"], treasure_deck=["cost7", "cost6"], card_decks={cid: c.deck for cid, c in catalog.items()})
    state.catalog_version, state.catalog_digest = release.version, release.digest
    if phase.startswith("combat"):
        state.combat = CombatState(fighter_ids=[11], monster_ids=["enemy"])
    repo = MemoryRepository()
    repo.create(state, Random(2))
    for uid in (11, 22):
        repo.link_private(uid, uid)
    return repo, Router(repo, release, "dota_bot")


def actions(view):
    return [b for row in view.rows for b in row]


def test_carried_no_value_item_is_visible_and_can_be_carried_on_other_turn():
    repo, router = fixture()
    s = repo.games["g"].state
    s.active_user_id = 22
    s.players[11].hand.append("pretty_balloons")
    router.route_update(message(11, 11, "/hand", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="card:pretty_balloons"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "carry_item", actor=11, card_id="pretty_balloons"), 11, 3), now=NOW)
    assert "pretty_balloons" in repo.get("g").state.players[11].in_play
    view = render_view(repo.get("g").state, 11, "equipment", router.release, now=NOW)
    assert "pretty_balloons" in view.text and "Нет стоимости" in view.text
    assert not any(b.action == "equip" and b.args["card_id"] == "pretty_balloons" for b in actions(view))


def test_valued_one_shots_are_available_in_sale_and_trade_selectors():
    repo, router = fixture()
    router.release.catalog["shot"] = CardDef("shot", "treasure", "one_shot", "Зелье", value=500)
    s = repo.games["g"].state
    s.players[11].hand.append("shot")
    sale = render_selection(s, 11, "sell", {"selected": ["shot", "cost0"]}, router.release, now=NOW)
    assert any(b.action == "sell" for b in actions(sale))
    s.players[11].hand.remove("shot")
    s.players[11].in_play.append("shot")
    trade = render_selection(s, 11, "trade", {"partner_id": 22, "offered_ids": ["shot"]}, router.release, now=NOW)
    assert any(b.action == "offer_trade" for b in actions(trade))


def test_dwarf_charity_and_group_totals_use_shared_rules():
    repo, router = fixture(race="dwarf")
    s = repo.games["g"].state
    s.phase = "turn.charity"
    s.players[11].hand = [f"cost{i}" for i in range(6)]
    view = render_view(s, 11, "main", router.release, now=NOW)
    assert "Лимит руки: 6" in view.text
    assert not any(b.args.get("flow") == "charity" for b in actions(view))
    s.phase = "combat.active"
    s.combat = CombatState(fighter_ids=[11], monster_ids=["bigfoot"])
    group = render_view(s, 11, "group", router.release, now=NOW)
    # Printed Level 12 and +3 against Dwarf/Halfling in the accepted manifest.
    assert "Противники: 15" in group.text


def test_wizard_charm_uses_entire_hand_with_russian_source_label():
    repo, router = fixture(role="wizard", phase="combat.active")
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    choice = button(repo, "select", actor=11, ability_key="wizard_charm")
    assert "wizard_charm" not in next(b["text"] for row in repo.outbox[-1]["payload"]["reply_markup"]["inline_keyboard"] for b in row if b.get("callback_data") == choice.token)
    router.route_update(press(choice, 11, 2), now=NOW)
    use = button(repo, "use_ability", actor=11, ability_key="wizard_charm")
    assert use.args["cost_ids"] == ["cost0", "cost1", "cost2", "cost3"]
    router.route_update(press(use, 11, 3), now=NOW)
    assert repo.get("g").state.players[11].level == 4
    assert repo.get("g").state.combat is None


def test_wizard_stored_roll_exposes_flight_then_explicit_resolution_only():
    repo, router = fixture(role="wizard", phase="combat.run_away")
    s = repo.games["g"].state
    s.combat.escape_pending = {(11, "enemy")}
    repo.games["g"].rng = Random(0)  # First accepted die is 4.
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    router.route_update(press(button(repo, "run_away", actor=11), 11, 2), now=NOW)
    s = repo.get("g").state
    assert s.combat.escape_rolls == {(11, "enemy"): 4}
    view = render_view(s, 11, "main", router.release, now=NOW)
    assert "Бросок: 4" in view.text
    assert not any(b.action == "run_away" for b in actions(view))
    router.route_update(press(button(repo, "select", actor=11, ability_key="wizard_flight"), 11, 3), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, cost_ids=["cost0"]), 11, 4), now=NOW)
    use = button(repo, "use_ability", actor=11, ability_key="wizard_flight")
    router.route_update(press(use, 22, 5), now=NOW)
    assert repo.get("g").version == 1
    router.route_update(press(use, 11, 6), now=NOW)
    assert repo.get("g").state.combat.escape_bonuses[(11, "enemy")] == 1
    router.route_update(press(use, 11, 7), now=NOW)
    assert repo.get("g").version == 2
    router.route_update(press(button(repo, "resolve_escape", actor=11), 11, 8), now=NOW)
    assert repo.get("g").state.players[11].level == 4
    assert repo.get("g").state.combat is None


def test_automatic_carried_rat_pays_only_its_source():
    repo, router = fixture(phase="combat.run_away")
    s = repo.games["g"].state
    s.players[11].in_play.append("rat_on_a_stick")
    s.combat.escape_pending = {(11, "enemy")}
    router.route_update(message(11, 11, "/game", 1), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, ability_key="rat_on_a_stick_escape"), 11, 2), now=NOW)
    use = button(repo, "use_ability", actor=11, ability_key="rat_on_a_stick_escape")
    assert use.args["cost_ids"] == ["rat_on_a_stick"]
    router.route_update(press(use, 11, 3), now=NOW)
    assert "rat_on_a_stick" in repo.get("g").state.treasure_discard
    assert repo.get("g").state.players[11].hand == ["cost0", "cost1", "cost2", "cost3"]


def test_hireling_swap_from_rendered_equipment_keeps_former_item_carried():
    repo, router = fixture()
    s = repo.games["g"].state
    s.players[11].in_play = ["hireling", "cost4"]
    s.players[11].equipped = ["cost4"]
    s.players[11].hireling_items = {"hireling": "cost4"}
    router.route_update(message(11, 11, "/equipment", 1), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, flow="hireling", hireling_id="hireling"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "assign_hireling", actor=11, card_id="cost0"), 11, 3), now=NOW)
    p = repo.get("g").state.players[11]
    assert p.hireling_items == {"hireling": "cost0"}
    assert "cost4" in p.in_play and "cost4" not in p.equipped


def test_cheat_selects_own_hand_item_without_revealing_foreign_hand():
    repo, router = fixture()
    repo.games["g"].state.players[11].hand.append("cheat")
    router.route_update(message(11, 11, "/hand", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="card:cheat"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "choose_card_target", actor=11, card_id="cheat"), 11, 3), now=NOW)
    play = button(repo, "play_card", actor=11, target={"player_id": 11, "card_id": "cost0"})
    router.route_update(press(play, 11, 4), now=NOW)
    assert repo.get("g").state.players[11].attachments == {"cheat": "cost0"}
    assert not any("Чужая тайна" in str(m["payload"]) for m in repo.outbox if m["payload"].get("chat_id") in {11, -100})


def test_dual_enabler_discard_requires_visible_exact_owner_identity_choices():
    repo, router = fixture(race="dwarf")
    s = repo.games["g"].state
    s.players[11].in_play += ["elf", "half_breed"]
    s.players[11].race_ids.append("elf")
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    router.route_update(press(button(repo, "discard_identity", actor=11, card_id="half_breed"), 11, 2), now=NOW)
    assert repo.get("g").state.players[11].pending_identity_excess == {"race": 1}
    forced = button(repo, "select", actor=11, flow="identity_excess")
    router.route_update(press(forced, 11, 3), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, selected=["elf"]), 11, 4), now=NOW)
    router.route_update(press(button(repo, "resolve_identity_excess", actor=11), 11, 5), now=NOW)
    assert repo.get("g").state.players[11].race_ids == ["dwarf"]


def test_big_excess_transfer_is_iterative_and_discard_hidden_when_receiver_exists():
    repo, router = fixture()
    s = repo.games["g"].state
    for i in (0, 1, 2):
        router.release.catalog[f"big{i}"] = CardDef(f"big{i}", "treasure", "item", f"Большая {i}", value=500, size="big")
    s.players[11].in_play = ["big0", "big1", "big2"]
    s.players[11].pending_big_excess = 2
    router.route_update(message(11, 11, "/game", 1), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, flow="big_excess"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, selected=["big0"]), 11, 3), now=NOW)
    transfer = button(repo, "resolve_big_items", actor=11, recipient_id=22)
    assert not any(b.action == "resolve_big_items" and "recipient_id" not in b.args for b in actions(render_selection(s, 11, "big_excess", {"selected": ["big0"]}, router.release, now=NOW)))
    router.route_update(press(transfer, 11, 4), now=NOW)
    assert repo.get("g").state.players[11].pending_big_excess == 1
    assert repo.get("g").state.players[22].in_play == ["big0"]
    router.route_update(press(button(repo, "select", actor=11, flow="big_excess"), 11, 5), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, selected=["big1"]), 11, 6), now=NOW)
    discard = button(repo, "resolve_big_items", actor=11, card_ids=["big1"])
    assert "recipient_id" not in discard.args
    router.route_update(press(discard, 11, 7), now=NOW)
    assert repo.get("g").state.players[11].pending_big_excess == 0
    assert "big1" in repo.get("g").state.treasure_discard


def test_cleric_door_prepayment_resurrects_old_top_before_discarding_cost():
    repo, router = fixture(role="cleric")
    s = repo.games["g"].state
    s.door_discard = ["secret"]
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, ability_key="cleric_resurrection"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, cost_ids=["cost0"]), 11, 3), now=NOW)
    router.route_update(press(button(repo, "use_ability", actor=11, target={"deck": "door"}), 11, 4), now=NOW)
    assert repo.get("g").state.phase == "turn.after_door"
    assert repo.get("g").state.door_deck == ["enemy"]
    assert "cost0" in repo.get("g").state.treasure_discard


def test_lobby_sex_is_optional_private_owner_choice():
    repo, router = fixture(phase="lobby")
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    choice = button(repo, "set_character_sex", actor=11, character_sex="female")
    router.route_update(press(choice, 22, 2), now=NOW)
    assert repo.get("g").state.players[11].character_sex is None
    router.route_update(press(choice, 11, 3), now=NOW)
    assert repo.get("g").state.players[11].character_sex == "female"


def test_combat_hireling_menu_has_no_illegal_assignment_selector():
    repo, router = fixture(phase="combat.active")
    s = repo.games["g"].state
    s.players[11].in_play.append("hireling")
    view = render_view(s, 11, "equipment", router.release, now=NOW)
    assert not any(b.args.get("flow") == "hireling" for b in actions(view))


def test_cleric_door_selector_discloses_face_up_top_and_payment_zone():
    repo, router = fixture(role="cleric")
    s = repo.games["g"].state
    s.door_discard = ["secret"]
    view = render_selection(s, 11, "ability", {"ability_key": "cleric_resurrection"}, router.release, now=NOW)
    assert "Чужая тайна" in view.text
    assert "из руки" in view.text


def test_halfling_sale_preview_and_commit_follow_actual_double_value():
    repo, router = fixture(race="halfling")
    router.route_update(message(11, 11, "/prices", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="sell"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, selected=["cost0"]), 11, 3), now=NOW)
    assert "Получите уровней: 1" in repo.outbox[-1]["payload"]["text"]
    router.route_update(press(button(repo, "sell", actor=11), 11, 4), now=NOW)
    assert repo.get("g").state.players[11].level == 5


def test_warrior_uses_open_cost_but_source_and_reserved_cards_are_not_offered():
    repo, router = fixture(role="warrior", phase="combat.active")
    s = repo.games["g"].state
    s.players[11].in_play.append("cost4")
    s.pending_initial_triggers = [(11, "cost0")]
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, ability_key="warrior_berserk"), 11, 2), now=NOW)
    costs = [b.args.get("cost_ids") for b in actions(render_selection(s, 11, "ability", {"ability_key": "warrior_berserk"}, router.release, now=NOW))]
    assert ["warrior"] not in costs and ["cost0"] not in costs
    router.route_update(press(button(repo, "select", actor=11, cost_ids=["cost4"]), 11, 3), now=NOW)
    router.route_update(press(button(repo, "use_ability", actor=11), 11, 4), now=NOW)
    assert repo.get("g").state.combat.temporary_strength == {11: 1}
    assert "cost4" in repo.get("g").state.treasure_discard


def test_thief_target_is_open_small_item_and_never_foreign_hand():
    repo, router = fixture(role="thief")
    s = repo.games["g"].state
    s.players[22].in_play.append("cost4")
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, ability_key="thief_theft"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, cost_ids=["cost0"]), 11, 3), now=NOW)
    steal = button(repo, "use_ability", actor=11, target={"player_id": 22, "card_id": "cost4"})
    repo.games["g"].rng = Random(0)
    router.route_update(press(steal, 11, 4), now=NOW)
    assert "cost4" in repo.get("g").state.players[11].in_play
    assert repo.get("g").state.players[22].hand == ["secret"]
    assert not any("Чужая тайна" in str(m["payload"]) for m in repo.outbox if m["payload"].get("chat_id") in {11, -100})


@pytest.mark.parametrize("die,retry", [(3, True), (5, False)])
def test_halfling_retry_menu_only_after_failed_own_roll(die, retry):
    repo, router = fixture(race="halfling", phase="combat.run_away")
    s = repo.games["g"].state
    s.combat.escape_pending = {(11, "enemy")}
    s.combat.escape_rolls = {(11, "enemy"): die}
    router.route_update(message(11, 11, "/game", 1), now=NOW)
    choices = [b for b in actions(render_view(s, 11, "main", router.release, now=NOW)) if b.args.get("ability_key") == "halfling_escape_retry"]
    assert bool(choices) == retry
    if retry:
        router.route_update(press(button(repo, "select", actor=11, ability_key="halfling_escape_retry"), 11, 2), now=NOW)
        router.route_update(press(button(repo, "select", actor=11, cost_ids=["cost0"]), 11, 3), now=NOW)
        router.route_update(press(button(repo, "use_ability", actor=11), 11, 4), now=NOW)
        result = repo.get("g").state
        assert result.combat.escape_uses[(11, "enemy", "halfling_escape_retry")] == 1
        assert not any(b.args.get("ability_key") == "halfling_escape_retry" for b in actions(render_view(result, 11, "main", router.release, now=NOW)))


def test_big_excess_can_be_sold_with_other_item_after_legal_threshold():
    repo, router = fixture()
    s = repo.games["g"].state
    for cid in ("big0", "big1"):
        router.release.catalog[cid] = CardDef(cid, "treasure", "item", cid, value=500, size="big")
    s.players[11].in_play = ["big0", "big1"]
    s.players[11].pending_big_excess = 1
    router.route_update(message(11, 11, "/game", 1), now=NOW)
    router.route_update(press(button(repo, "nav", actor=11, screen="sell"), 11, 2), now=NOW)
    router.route_update(press(button(repo, "select", actor=11, selected=["big0"]), 11, 3), now=NOW)
    assert not any(b.action == "sell" for b in actions(render_selection(s, 11, "sell", {"selected": ["big0"]}, router.release, now=NOW)))
    router.route_update(press(button(repo, "select", actor=11, selected=["big0", "cost0"]), 11, 4), now=NOW)
    router.route_update(press(button(repo, "sell", actor=11), 11, 5), now=NOW)
    assert repo.get("g").state.players[11].pending_big_excess == 0
    assert repo.get("g").state.players[11].level == 5


@pytest.mark.parametrize("mismatch", ["actor", "chat", "version", "game", "expired"])
def test_character_selection_rejects_context_mismatch_without_state_rng_change(mismatch):
    from datetime import timedelta
    repo, router = fixture(role="warrior", phase="combat.active")
    router.route_update(message(11, 11, "/character", 1), now=NOW)
    select = button(repo, "select", actor=11, ability_key="warrior_berserk")
    update = press(select, 11, 2)
    when = NOW
    if mismatch == "actor":
        update["callback_query"]["from"]["id"] = 22
    elif mismatch == "chat":
        update["callback_query"]["message"]["chat"]["id"] = -100
    elif mismatch == "version":
        repo.games["g"].version += 1
    elif mismatch == "game":
        from dataclasses import replace
        repo.intents[select.token] = replace(select, game_id="another")
    else:
        when += timedelta(seconds=121)
    before = deepcopy(repo.games["g"])
    router.route_update(update, now=when)
    assert repo.get("g").state == before.state
    assert repo.get("g").rng.getstate() == before.rng.getstate()
    assert "show_alert" in repo.outbox[-1]["payload"]
