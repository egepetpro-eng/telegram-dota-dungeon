# Classic Dota v1 factual source audit

Verified on 2026-10-08. The compiled data release preserves this factual manifest;
runtime release acceptance still requires Task 5/6 handlers and behavior tests.

## Scope and evidence standard

147 distinct definitions represent 168 physical classic cards: 75 Door definitions / 95 Door copies, 72 Treasure definitions / 73 Treasure copies. Every definition is now `verified`. Repetitions come from a separately captured publisher checklist, not from the production manifest. No missing price or reward is filled from recollection. All original card names are audit identifiers; Dota IDs and Russian names are presentation mappings.

Evidence is the visible original publisher-authored face (including a physical card photograph hosted elsewhere), an official correction, or the official rules. Retailer commentary, search image captions and fan wiki paraphrases were not used as factual evidence. These third-party hosts are transport for original card content; they are not the authors of the rules. Card text is represented as facts and compact selectors, not copied full descriptions.

Non-item value zero is a nonapplicable contract default, not a printed sale value. Likewise, one level is the publisher rule's default monster reward and the required contract default for non-monsters; it is not a reward of non-monster cards. Null slot and trigger mean not applicable, not an unresolved fact. `bonus` is the printed monster level for monsters and the equipment bonus for items; temporary strength changes remain in effects.

## Primary sources inspected

- [Publisher classic checklist and second-printing corrections](https://www.munchkin.game/products/games/munchkin/). Lists every repeated physical card. Fixture preserves the printed order and repeats and records HTML SHA-256 `5ffe86cc38eec709464e751bf3982ab4f14f9c444e246a4d4931724adbf2c652`.
- [Publisher rules, July 2019 v1.8](https://munchkin.game/site-munchkin/assets/files/1138/munchkin_rules-1.pdf): common play timing, sale/item categories, ordinary monster levels/rewards and identity abilities; example also supplies Net Troll 10/3, Chainsaw +3, Missile +5, Enraged +5/+1 Treasure, Boots +2.
- [Publisher FAQ, April 2020](https://munchkin.game/gameplay/faq/): exceptions and timing, including Amazon, compulsory effects, escape items, multiple monsters and class abilities.
- [Publisher 2010 correction log](https://munchkin.game/gameplay/faq/changelog.html/): revised Wizard, Halfling, Cleric, Hireling, Kneepads, Tuba, title and escape handling. Corrections take priority over older yellow scans.
- [Publisher-authored Munchkin Thingies v3.2, 2014, pages 2-3, mirrored](https://www.scribd.com/document/244388270/Munchkin-Thingies): complete core class/race abilities, editorial credits and version visible.
- [Publisher Thief article](https://munchkin.game/news/2021/december/munchkin-spotlight-class-thief/): theft/backstab costs, roll, timing and limits.
- [Publisher Rigged Demo rules](https://www.munchkin.game/site-munchkin/assets/files/1419/rigged_demo_rules.pdf): original example monsters/modifiers and Mutilate timing.
- [Original physical base-deck photograph gallery](https://www.ebay.com/itm/377267085064): 18 photographs; inspected original high-resolution faces (1600 px URLs appear per record). These show post-2010 colored cards, including current class texts and item restrictions/prices.
- [Original yellow base-deck scan index](https://net-clan.com/PDFS/Munchkin/index.htm): 11 Door / 9 Treasure sheets. Inspected Door sheets 1-11; selected missing faces supply Amazon, Baby, Cheat, Crabs, Change Sex, Tongue Demon and Undead Horse. Older identity/correction text was superseded by publisher corrections/current faces.
- [Original assembled Treasure face grid](https://worksheets.clipart-library.com/images2/printable-munchkin-cards/printable-munchkin-cards-0.jpg): inspected all seven rows at natural size, supplying 68/72 Treasure definitions. [Second sheet](https://worksheets.clipart-library.com/images2/printable-munchkin-cards/printable-munchkin-cards-1.jpg) supplies Kill the Hireling; photos confirm remaining items and prices.
- [Original eight-card photograph](https://miro.medium.com/v2/resize%3Afit%3A1200/1%2Atw3zt0WlLZZ1jDYJ8JsyIQ.jpeg): Wizard, Halfling, Gazebo, small-item curse, Hoard, Rapier, Missile and Kneepads.

## Corrections and interpretation decisions

- Shield of Ubiquity is **600**, **Big**, one Hand, +4, Warrior only. A low-resolution reading was replaced by the clearly printed physical face.
- Rat on a Stick retains the Level **8 or below** escape limit; it may be sacrificed from carried cards even when not equipped. Its escape is an ability, not an effect fired by equipping it.
- Wizard charm spends the **entire hand**, minimum three cards. Cost mode is `all_hand`; three is the eligibility minimum, not a fixed price. Flight is applied after the escape die.
- Kneepads cannot be used by Clerics, force only a **strictly higher-level** helper, and cannot force a helper for the wearer's winning level. The photographed face supplies this precise comparison.
- Mutilate the Bodies requires **after a combat**, not after killing a monster. Whine cannot be used by anyone tied for highest level.
- Ordinary Go Up a Level cards, including Boil an Anthill, may target any player who can legally gain the level. The publisher FAQ permits another recipient; these cards still cannot grant the winning level.
- Really Impressive Title and Hireling are not saleable Items. Limburger and Anchovy Sandwich is permanent Halfling equipment. Doppleganger is a 300-value one-shot Item.
- Ghoulfiends are not Undead and use level-only combat. Mr. Bones, King Tut, Undead Horse and Wight Brothers carry the printed Undead tag.
- Baby uses a special descriptor to preserve both floors: monster level minimum one and Treasure minimum one. The -5 and -1 adjustments never discard those floors.
- King Tut / Wight Brothers charge two levels when fleeing even on successful escape; their low-level no-pursuit exception remains separate. Floating Nose and Crabs cannot be outrun.
- Original fire/flame names supply stable source tags for the Chicken bonus; Dota presentation names never control these rules.

## Accepted Dota mappings

Mappings are thematic replacements only. Original prices, bonuses, rewards, source identity keys and conditions remain classic. Four classes map to distinct heroes (Axe, Riki, Omniknight, Crystal Maiden). Neutral/lane creep opponents include melee creep, Kobold, Harpy Stormcrafter and Mud Golem; Plutonium Dragon maps to Roshan. Magic Lamp maps to Smoke of Deceit. Repeated physical copies share one mapping. Media evidence belongs to the separate media audit.

| Rule key | Original identity | Deck / copies | Dota entity | Russian display | Evidence |
|---|---|---|---|---|---|
| 3_872_orcs | 3,872 Orcs | door / 1 | creep:melee_creep | Отряд крипов | verified |
| amazon | Amazon | door / 1 | hero:enchantress | Чародейка | verified |
| ancient | Ancient | door / 1 | hero:elder_titan | Древняя сила | verified |
| baby | Baby | door / 1 | hero:invoker | Уменьшение | verified |
| bigfoot | Bigfoot | door / 1 | hero:tiny | Тини | verified |
| bullrog | Bullrog | door / 1 | hero:doom | Дум | verified |
| cheat | Cheat! | door / 1 | hero:rubick | Приём: Рубик | verified |
| cleric | Cleric | door / 3 | hero:omniknight | Омникнайт | verified |
| crabs | Crabs | door / 1 | hero:broodmother | Брудмазер | verified |
| curse_change_class | Curse! Change Class | door / 1 | hero:rubick | Проклятие: Рубик | verified |
| curse_change_race | Curse! Change Race | door / 1 | hero:morphling | Проклятие: Морфлинг | verified |
| curse_change_sex | Curse! Change Sex | door / 1 | hero:puck | Проклятие: Пак | verified |
| curse_chicken_on_your_head | Curse! Chicken on Your Head | door / 1 | hero:shadow_shaman | Проклятие: Шэдоу Шаман | verified |
| curse_duck_of_doom | Curse! Duck of Doom | door / 1 | hero:grimstroke | Проклятие: Гримстроук | verified |
| curse_income_tax | Curse! Income Tax | door / 1 | hero:bounty_hunter | Проклятие: Баунти Хантер | verified |
| curse_lose_a_big_item | Curse! Lose a Big Item | door / 1 | hero:tiny | Проклятие: Тини | verified |
| curse_lose_a_level | Curse! Lose a Level | door / 2 | hero:shadow_demon | Проклятие: Шэдоу Демон | verified |
| curse_lose_a_small_item | Curse! Lose a Small Item | door / 2 | hero:slark | Проклятие: Сларк | verified |
| curse_lose_the_armor_you_are_wearing | Curse! Lose the Armor You Are Wearing | door / 1 | hero:razor | Проклятие: Разор | verified |
| curse_lose_the_footgear_you_are_wearing | Curse! Lose the Footgear You Are Wearing | door / 1 | hero:dark_seer | Проклятие: Дарк Сир | verified |
| curse_lose_the_headgear_you_are_wearing | Curse! Lose the Headgear You Are Wearing | door / 1 | hero:silencer | Проклятие: Сайленсер | verified |
| curse_lose_two_cards | Curse! Lose Two Cards | door / 1 | hero:lion | Проклятие: Лион | verified |
| curse_lose_your_class | Curse! Lose Your Class | door / 1 | hero:death_prophet | Проклятие: Дэс Профет | verified |
| curse_lose_your_race | Curse! Lose Your Race | door / 1 | hero:morphling | Проклятие: Морфлинг | verified |
| curse_malign_mirror | Curse! Malign Mirror | door / 1 | hero:terrorblade | Проклятие: Террорблейд | verified |
| divine_intervention | Divine Intervention | door / 1 | hero:chen | Приём: Чен | verified |
| drooling_slime | Drooling Slime | door / 1 | hero:venomancer | Веномансер | verified |
| dwarf | Dwarf | door / 3 | hero:sniper | Народ: Снайпер | verified |
| elf | Elf | door / 3 | hero:windranger | Народ: Виндренджер | verified |
| enraged | Enraged | door / 1 | hero:huskar | Ярость Хускара | verified |
| face_sucker | Face Sucker | door / 1 | hero:pudge | Пудж | verified |
| floating_nose | Floating Nose | door / 1 | hero:bane | Бэйн | verified |
| flying_frogs | Flying Frogs | door / 1 | hero:puck | Пак | verified |
| gazebo | Gazebo | door / 1 | hero:treant_protector | Трент | verified |
| gelatinous_octahedron | Gelatinous Octahedron | door / 1 | hero:enigma | Энигма | verified |
| ghoulfiends | Ghoulfiends | door / 1 | hero:necrophos | Некрофос | verified |
| half_breed | Half-Breed | door / 2 | hero:morphling | Приём: Морфлинг | verified |
| halfling | Halfling | door / 3 | hero:meepo | Народ: Мипо | verified |
| harpies | Harpies | door / 1 | creep:harpy_stormcrafter | Гарпия-буревестница | verified |
| help_me_out_here | Help Me Out Here! | door / 1 | hero:chen | Приём: Чен | verified |
| hippogriff | Hippogriff | door / 1 | hero:phoenix | Феникс | verified |
| humongous | Humongous | door / 1 | hero:undying | Разрастание | verified |
| illusion | Illusion | door / 1 | hero:phantom_lancer | Приём: Фантом Лансер | verified |
| insurance_salesman | Insurance Salesman | door / 1 | hero:alchemist | Алхимик | verified |
| intelligent | Intelligent | door / 1 | hero:oracle | Прозрение Оракула | verified |
| king_tut | King Tut | door / 1 | hero:sand_king | Сэнд Кинг | verified |
| lame_goblin | Lame Goblin | door / 1 | creep:kobold | Кобольд | verified |
| large_angry_chicken | Large Angry Chicken | door / 1 | hero:phoenix | Огненный Феникс | verified |
| lawyers | Lawyers | door / 1 | hero:alchemist | Сделка Алхимика | verified |
| leperchaun | Leperchaun | door / 1 | hero:nature_prophet | Фурион | verified |
| mate | Mate | door / 1 | hero:naga_siren | Приём: Нага Сирена | verified |
| maul_rat | Maul Rat | door / 1 | hero:hoodwink | Худвинк | verified |
| mr_bones | Mr. Bones | door / 1 | hero:wraith_king | Король мёртвых | verified |
| net_troll | Net Troll | door / 1 | hero:troll_warlord | Тролль-полководец | verified |
| out_to_lunch | Out to Lunch | door / 1 | hero:ogre_magi | Приём: Огр Маг | verified |
| pit_bull | Pit Bull | door / 1 | hero:lycan | Ликан | verified |
| platycore | Platycore | door / 1 | hero:primal_beast | Первобытный зверь | verified |
| plutonium_dragon | Plutonium Dragon | door / 1 | creep:roshan | Рошан | verified |
| potted_plant | Potted Plant | door / 1 | hero:treant_protector | Молодой Трент | verified |
| pukachu | Pukachu | door / 1 | hero:storm_spirit | Шторм Спирит | verified |
| shrieking_geek | Shrieking Geek | door / 1 | hero:tinker | Тинкер | verified |
| snails_on_speed | Snails on Speed | door / 1 | hero:weaver | Вивер | verified |
| squidzilla | Squidzilla | door / 1 | hero:tidehunter | Тайдхантер | verified |
| stoned_golem | Stoned Golem | door / 1 | creep:mud_golem | Грязевой голем | verified |
| super_munchkin | Super Munchkin | door / 2 | hero:arc_warden | Приём: Арк Варден | verified |
| thief | Thief | door / 3 | hero:riki | Рики | verified |
| tongue_demon | Tongue Demon | door / 1 | hero:shadow_demon | Шэдоу Демон | verified |
| truly_obnoxious_curse | Truly Obnoxious Curse! | door / 1 | hero:doom | Проклятие: Дум | verified |
| undead_horse | Undead Horse | door / 1 | hero:chaos_knight | Рыцарь Хаоса | verified |
| unspeakably_awful_indescribable_horror | Unspeakably Awful Indescribable Horror | door / 1 | hero:faceless_void | Фэйслесс Войд | verified |
| wandering_monster | Wandering Monster | door / 3 | hero:beastmaster | Приём: Бистмастер | verified |
| wannabe_vampire | Wannabe Vampire | door / 1 | hero:night_stalker | Найт Сталкер | verified |
| warrior | Warrior | door / 3 | hero:axe | Акс | verified |
| wight_brothers | Wight Brothers | door / 1 | hero:visage | Визаж | verified |
| wizard | Wizard | door / 3 | hero:crystal_maiden | Кристал Мейден | verified |
| 1_000_gold_pieces | 1,000 Gold Pieces (GUAL) | treasure / 1 | item:hand_of_midas | Рука Мидаса | verified |
| bad_ass_bandana | Bad-Ass Bandana | treasure / 1 | item:band_of_elvenskin | Повязка ловкости | verified |
| boil_an_anthill | Boil an Anthill (GUAL) | treasure / 1 | item:radiance | Радианс | verified |
| boots_of_butt_kicking | Boots of Butt-Kicking | treasure / 1 | item:phase_boots | Фазовые сапоги | verified |
| boots_of_running_really_fast | Boots of Running Really Fast | treasure / 1 | item:boots_of_travel | Сапоги путешествия | verified |
| bow_with_ribbons | Bow with Ribbons | treasure / 1 | item:butterfly | Бабочка | verified |
| bribe_gm_with_food | Bribe GM With Food (GUAL) | treasure / 1 | item:enchanted_mango | Манго для наставника | verified |
| broad_sword | Broad Sword | treasure / 1 | item:broadsword | Широкий меч | verified |
| buckler_of_swashing | Buckler of Swashing | treasure / 1 | item:buckler | Баклер | verified |
| chainsaw_of_bloody_dismemberment | Chainsaw of Bloody Dismemberment | treasure / 1 | item:battle_fury | Боевая ярость | verified |
| cheese_grater_of_peace | Cheese Grater of Peace | treasure / 1 | item:desolator | Дезолятор | verified |
| cloak_of_obscurity | Cloak of Obscurity | treasure / 1 | item:shadow_amulet | Теневой амулет | verified |
| convenient_addition_error | Convenient Addition Error (GUAL) | treasure / 1 | item:hand_of_midas | Выгодная оценка | verified |
| cotion_of_ponfusion | Cotion of Ponfusion | treasure / 1 | item:diffusal_blade | Рассеивающий клинок | verified |
| dagger_of_treachery | Dagger of Treachery | treasure / 1 | item:blink_dagger | Кинжал предательства | verified |
| doppleganger | Doppleganger | treasure / 1 | item:manta_style | Манта | verified |
| electric_radioactive_acid_potion | Electric Radioactive Acid Potion | treasure / 1 | item:urn_of_shadows | Урна духов | verified |
| eleven_foot_pole | Eleven-Foot Pole | treasure / 1 | item:monkey_king_bar | Посох Короля обезьян | verified |
| flaming_armor | Flaming Armor | treasure / 1 | item:black_king_bar | Чёрный король | verified |
| flaming_poison_potion | Flaming Poison Potion | treasure / 1 | item:orb_of_venom | Ядовитая сфера | verified |
| flask_of_glue | Flask of Glue | treasure / 1 | item:rod_of_atos | Жезл Атоса | verified |
| freezing_explosive_potion | Freezing Explosive Potion | treasure / 1 | item:shivas_guard | Страж Шивы | verified |
| friendship_potion | Friendship Potion | treasure / 1 | item:healing_salve | Целебный бальзам | verified |
| gentleman_s_club | Gentleman's Club | treasure / 1 | item:skull_basher | Сокрушитель черепов | verified |
| hammer_of_kneecapping | Hammer of Kneecapping | treasure / 1 | item:abyssal_blade | Клинок бездны | verified |
| helm_of_courage | Helm of Courage | treasure / 1 | item:helm_of_iron_will | Железный шлем | verified |
| hireling | Hireling | treasure / 1 | item:helm_of_the_dominator | Союзник подчинения | verified |
| hoard | Hoard! | treasure / 1 | item:hand_of_midas | Добыча Мидаса | verified |
| horny_helmet | Horny Helmet | treasure / 1 | item:helm_of_the_overlord | Шлем властелина | verified |
| huge_rock | Huge Rock | treasure / 1 | item:enchanted_mango | Зачарованный плод | verified |
| instant_wall | Instant Wall | treasure / 1 | item:force_staff | Посох силы | verified |
| invisibility_potion | Invisibility Potion | treasure / 1 | item:shadow_amulet | Теневая завеса | verified |
| invoke_obscure_rules | Invoke Obscure Rules (GUAL) | treasure / 1 | item:aghanims_scepter | Секрет Аганима | verified |
| kill_the_hireling | Kill the Hireling (GUAL) | treasure / 1 | item:dagon | Плата Дагону | verified |
| kneepads_of_allure | Kneepads of Allure | treasure / 1 | item:bloodthorn | Кровавый шип | verified |
| leather_armor | Leather Armor | treasure / 1 | item:ring_of_protection | Защитное кольцо | verified |
| limburger_and_anchovy_sandwich | Limburger and Anchovy Sandwich | treasure / 1 | item:cheese | Сыр | verified |
| loaded_die | Loaded Die | treasure / 1 | item:talisman_of_evasion | Талисман уклонения | verified |
| mace_of_sharpness | Mace of Sharpness | treasure / 1 | item:sacred_relic | Священная реликвия | verified |
| magic_lamp | Magic Lamp | treasure / 1 | item:smoke_of_deceit | Дым обмана | verified |
| magic_missile | Magic Missile | treasure / 1 | item:magic_wand | Волшебная ракета | verified |
| mithril_armor | Mithril Armor | treasure / 1 | item:assault_cuirass | Штурмовая кираса | verified |
| mutilate_the_bodies | Mutilate the Bodies (GUAL) | treasure / 1 | item:battle_fury | Трофеи ярости | verified |
| nasty_tasting_sports_drink | Nasty-Tasting Sports Drink | treasure / 1 | item:bottle | Бутыль | verified |
| pantyhose_of_giant_strength | Pantyhose of Giant Strength | treasure / 1 | item:belt_of_strength | Пояс силы | verified |
| pointy_hat_of_power | Pointy Hat of Power | treasure / 1 | item:crown | Корона | verified |
| pollymorph_potion | Pollymorph Potion | treasure / 1 | item:scythe_of_vyse | Коса Вайса | verified |
| potion_of_general_studliness | Potion of General Studliness (GUAL) | treasure / 1 | item:moon_shard | Лунный осколок | verified |
| potion_of_halitosis | Potion of Halitosis | treasure / 1 | item:orb_of_corrosion | Сфера разложения | verified |
| potion_of_idiotic_bravery | Potion of Idiotic Bravery | treasure / 1 | item:mask_of_madness | Маска безумия | verified |
| pretty_balloons | Pretty Balloons | treasure / 1 | item:faerie_fire | Волшебная искра | verified |
| rapier_of_unfairness | Rapier of Unfairness | treasure / 1 | item:divine_rapier | Божественная рапира | verified |
| rat_on_a_stick | Rat on a Stick | treasure / 1 | item:javelin | Копьё | verified |
| really_impressive_title | Really Impressive Title | treasure / 1 | item:aegis | Титул бессмертного | verified |
| sandals_of_protection | Sandals of Protection | treasure / 1 | item:boots_of_bearing | Сапоги знаменосца | verified |
| shield_of_ubiquity | Shield of Ubiquity | treasure / 1 | item:vanguard | Авангард | verified |
| short_wide_armor | Short Wide Armor | treasure / 1 | item:platemail | Латный доспех | verified |
| singing_dancing_sword | Singing & Dancing Sword | treasure / 1 | item:sange_and_yasha | Саша и Яша | verified |
| sleep_potion | Sleep Potion | treasure / 1 | item:euls_scepter | Скипетр ветров | verified |
| slimy_armor | Slimy Armor | treasure / 1 | item:chainmail | Кольчуга | verified |
| sneaky_bastard_sword | Sneaky Bastard Sword | treasure / 1 | item:shadow_blade | Теневой клинок | verified |
| spiky_knees | Spiky Knees | treasure / 1 | item:blade_mail | Колючая броня | verified |
| staff_of_napalm | Staff of Napalm | treasure / 1 | item:aghanims_scepter | Скипетр Аганима | verified |
| steal_a_level | Steal a Level | treasure / 1 | item:hand_of_midas | Чужая награда | verified |
| stepladder | Stepladder | treasure / 1 | item:iron_branch | Железная ветвь | verified |
| swiss_army_polearm | Swiss Army Polearm | treasure / 1 | item:heavens_halberd | Небесная алебарда | verified |
| transferral_potion | Transferral Potion | treasure / 1 | item:town_portal_scroll | Свиток переноса | verified |
| tuba_of_charm | Tuba of Charm | treasure / 1 | item:pipe_of_insight | Трубка прозрения | verified |
| wand_of_dowsing | Wand of Dowsing | treasure / 1 | item:magic_wand | Волшебная палочка | verified |
| whine_at_the_gm | Whine at the GM (GUAL) | treasure / 1 | item:hand_of_midas | Просьба о награде | verified |
| wishing_ring | Wishing Ring | treasure / 2 | item:lotus_orb | Сфера лотоса | verified |
| yuppie_water | Yuppie Water | treasure / 1 | item:clarity | Зелье ясности | verified |

## Remaining work and precise limits

No factual record remains unresolved. `catalog.json` now contains all 147 definitions,
original Russian descriptions, the accepted Dota mappings and 168 physical IDs in
`rule_key:copy_number` form. All 17 mechanics fields are copied exactly from each
verified source record. No callback key, number, condition or cost was changed to
accommodate absent runtime support.

The data compilation is complete; runtime support is not. Named special effects,
conditions, triggers and abilities still require real handlers, closed validators
and behavior tests before production acceptance. On the compilation branch based
on `316af736bf2b6eec29737df203cbf2e860e79692`, all four registries are empty and the
release loader correctly rejects `3_872_orcs.bad_stuff[0]` for unimplemented
`orcs_bad_stuff_die`. The exact dependent callback inventory below remains the
Task 5/6 handoff. The definition-keyed [behavior coverage ledger](classic-dota-v1-behavior-coverage.md)
identifies existing generic test evidence and explicitly pending real-catalog
scenarios for every card; pending names are proposals, not tests claimed to pass.

Older face evidence was reconciled with known publisher changes, but there is no publisher-hosted comprehensive current face archive. Re-inspection of an owned contemporary physical deck would improve source stability and edition assurance. Third-party image hosts may disappear; per-record URLs identify the exact face inspected. No card artwork was copied into this repository.

## Named runtime callbacks required by source

### effects

`add_monster_from_hand`, `all_clerics_gain_level`, `baby_modifier`, `cancel_curse`, `change_sex`, `chicken_on_head`, `discard_all_monsters_draw_treasures`, `discard_chosen_item`, `discard_equipped`, `discard_hireling`, `discard_largest_bonus_item`, `doppleganger`, `duplicate_monster`, `flask_of_glue`, `friendship_potion`, `half_breed`, `hireling`, `ignore_one_item_restrictions`, `income_tax`, `instant_wall`, `invisibility_potion`, `loaded_die`, `lose_class`, `lose_item`, `lose_race`, `magic_lamp`, `malign_mirror`, `pollymorph_potion`, `potion_of_halitosis`, `random_hand_cards_to_neighbors`, `replace_identity_from_discard`, `replace_monster`, `steal_a_level`, `super_munchkin`, `take_item_to_win`, `transferral_potion`, `wand_of_dowsing`, `yuppie_water`.

### bad_stuff

`choose_discard_hand_or_lose_levels`, `death`, `death_except_discard_wizard`, `discard_all_identity`, `discard_all_items`, `discard_armor_and_below_waist_items`, `discard_die_number_items_or_hand`, `discard_equipped`, `discard_equipped_or_lose_level`, `discard_hand`, `discard_items_value`, `items_chosen_by_neighbors`, `items_to_highest_players`, `lose_class_or_levels`, `lose_levels_race_variant`, `orcs_bad_stuff_die`, `random_hand_to_other_players`, `set_level`, `set_level_to_lowest_player`, `treasure_to_other_players`.

### conditions

`after_combat`, `amazon_female`, `automatic_escape`, `bonuses_only_combat`, `bribe_monster`, `cannot_run_away`, `cleric_chase_away`, `discard_item_before_combat`, `discard_weapon_pole_or_staff_to_escape`, `dwarf_carrying`, `elf_escape_bonus`, `elf_extra_treasure`, `elf_helper_level`, `escape_bonus`, `extra_level_if_fire_flame`, `extra_level_if_solo_without_bonuses`, `halfling_double_sale`, `hireling_carry_item`, `hireling_in_play`, `item_changes_losing_to_winning`, `item_escape_bonus`, `item_identity_bonus`, `kneepads_forced_help`, `level_only_combat`, `may_ignore_monster`, `monster_bonus`, `no_attack_and_exchange`, `no_helper`, `not_highest_level`, `own_turn_identity_play`, `participant_only`, `rat_escape_eligibility`, `requires_identity`, `run_away_loses_levels`, `sandals_door_curse_immunity`, `tuba_escape`, `warrior_wins_ties`, `will_not_pursue`.

### abilities

`cleric_resurrection`, `cleric_turn_undead`, `halfling_escape_retry`, `hireling_escape`, `rat_on_a_stick_escape`, `thief_backstab`, `thief_theft`, `warrior_berserk`, `wizard_charm`, `wizard_flight`.

### trigger

`hoard`, `mandatory_play`.

## Verification

TDD red: four missing-manifest failures; numeric-evidence failure for Net Troll; price-evidence failure for Magic Missile; Rat ability regression failed because it was an equip effect; GUAL recipient regression failed because Boil an Anthill was self-only. Green manifest suite: 8 passed. Full suite: 78 passed. Tests verify independent per-card copy counts, totals, evidence completeness, fixed factual examples, naming isolation, conditional escape representation and ordinary GUAL recipient eligibility.

Task 7 compilation checks in `tests/test_card_descriptions.py` first failed with
36 missing-catalog assertions. A subsequent timing regression failed when the
Magic Lamp description incorrectly said outside combat. Final compilation suite:
37 passed. These tests check factual compilation and presentation; they do not
substitute for actual card behavior coverage or assert that the release loads.

Fresh full suite on the compilation branch: `python -m pytest -q` — 343 passed,
16 skipped (real PostgreSQL integration requires `TEST_DATABASE_URL`). CLI
validation exits 1 for the expected unimplemented `orcs_bad_stuff_die`; there is
no runnable-release or wheel-install success claim at this stage. Canonical
compiled digest: `8ec08a4b28f273ba6149e2c6436baa4e7308c1f7a32e721fdb8c8f86343c49e8`.

Task 7 review correction clarifies that Invisibility Potion applies after the
user's own failed escape and automatically rescues only that user from all
monsters. Mechanics and accepted mappings remain exact. The recipient wording
regression failed before correction (1 failed, 37 passed); corrected description
suite: 38 passed. Current compiled digest after this presentation correction:
`32d2dedf9a6d1efc1cf415ce580baaa17eaa87cdeea4f062d985ebf9e2da14f1`.
Fresh full suite after the correction: 344 passed, 16 PostgreSQL integration
tests skipped for the same missing `TEST_DATABASE_URL` fixture requirement.
