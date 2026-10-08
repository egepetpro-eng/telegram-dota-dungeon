# Classic Dota v1 — M2 artwork selection draft

Research and inspection date: 2026-10-08. Worktree base: `a81b337678ecee459a5240edd3a2000b144b7a0f`. This delivers verified selections and complete **draft** definition bindings. `media.json` has `media_version: classic-dota-v1-draft-2` and `catalog_digest: null`. It is deliberately invalid for production acceptance until the coordinator supplies and pins the final playable catalog digest. Source facts remain A’s separate research task; media coverage does not imply mechanically verified cards.

## Coverage and selection

220 inventory assets: 219 verified, one candidate. Added 52 verified records in M2: 48 original item icons, three original neutral portraits and one official lane-creep promo. All M1 alternatives and named authorship records remain present; the unconfirmed Shadow Fiend loading-screen remains candidate and unselected.

147 definition bindings cover 168 physical copies using 127 unique selected assets/entities: 59 heroes, 63 items and five creeps. Selected asset kinds: 59 portraits, 63 icons, three promos, one wallpaper and one official illustration. Repeated physical copies inherit the same rule-key binding. Every binding matches the exact accepted canonical entity; no unrelated-hero substitution was used. Mapping read from A’s `source-manifest.json` after its five creep changes and Smoke of Deceit correction.

| Source rule | Accepted creep | Selected asset / limitation |
| --- | --- | --- |
| `3_872_orcs` | `creep:melee_creep` | Valve TI2019 Reptilian Refuge lane-creep promo. Cosmetic variant, not base-model portrait; blade-bearing green creep at left. Additional staff-bearing creature appears in full image. A explicitly accepted this variant with crop notes. |
| `harpies` | `creep:harpy_stormcrafter` | Original named 7.31 game portrait; actual filename `npc_dota_neutral_harpy_storm`. |
| `lame_goblin` | `creep:kobold` | Original named 7.31 game portrait `npc_dota_neutral_kobold`. |
| `stoned_golem` | `creep:mud_golem` | Original named 7.31 game portrait `npc_dota_neutral_mud_golem`. |
| `plutonium_dragon` | `creep:roshan` | Valve 2012 Diretide official illustration; seasonal pumpkin prop retained. |

Axe, Invoker and Hoodwink use the existing verified official promos/wallpaper; all other mapped heroes use their original same-entity portraits. Clockwerk’s Jonathan Lee loading-screen stays in inventory because no current definition maps to Clockwerk. Selection does not silently drop authored alternatives.

## M2 primary evidence

- [Valve itemlist API](https://www.dota2.com/datafeed/itemlist?language=english): read exact IDs, English names and internal `item_` names for all 48 missing mapped items.
- Each new item record links its exact original [itemdata API](https://www.dota2.com/datafeed/itemdata?language=english&item_id=17) endpoint. All 48 returned IDs/internal names/English labels were checked against the chosen entity, including aliases `ultimate_scepter`, `boots_of_elves`, `assault`, `blink`, `rapier`, `cyclone`, `flask`, `branches`, `manta`, `relic`, `sheepstick`, `invis_sword` and `tpscroll`.
- [Valve’s original site script](https://www.dota2.com/public/javascript/dota_react/main.js?v=K0KE9f72Ct4H&l=english&_cdn=akamai) declares item rendering with `IMG_URL + items/ + API name.replace("item_", "") + .png`, and neutral portraits with `IMG_URL + units/ + unit.name + .png`. This was read directly. The filename relationship is publisher-authored evidence, not inferred from successful requests.
- [Patch 7.27](https://www.dota2.com/patches/7.27), [7.31](https://www.dota2.com/patches/7.31), [7.33](https://www.dota2.com/patches/7.33) and [7.39](https://www.dota2.com/patches/7.39): inspected named item sections and exact rendered CSS image URLs. They independently expose icon/name pairs including Assault Cuirass, Aghanim’s Scepter, Shadow Blade, Eul’s Scepter, Manta Style, Scythe of Vyse and Boots of Bearing. 7.31 also supplies the three exact named neutral-creep portrait URLs. API identity and renderer evidence cover component icons absent from these named patch sections.
- [TI2019 Battle Pass](https://www.dota2.com/international2019/battlepass/): read `CustomCreep` statement naming equippable Reptilian Refuge Radiant/Dire lane creeps and exact `custom_creep_fg.png` image element; directly opened original PNG to inspect blade-bearing creep and multi-creep composition.

All 48 newly added item icons and three neutral portraits were visually inspected together with labels at 96x64. This check is additional to authoritative identity/provenance checks; availability alone was never treated as verification. Exact original filenames remain in `image_url`, while canonical entity IDs use accepted underscore slugs.

## Small-card inspection

All 127 selected originals were retrieved and inspected in a labelled sheet with maximum 112x64 image windows. Original hero/neutral face crops and item silhouettes remain recognizable. Iron Branch and Broadsword are thin silhouettes but readable on the original dark ground; Bottle/Clarity/Salve and the two helmets have distinct colours/shapes. Existing item icons remain source-verified M1 fallbacks.

Wide illustration/promo subjects become small when the whole canvas is fitted. Inspected proposed subject crops at maximum 120x96 improve recognizable faces, weapons and silhouettes. Normalized crop recommendations `(left, top, right, bottom)` are recorded in selected asset notes and below:

| Asset | Recommended crop |
| --- | --- |
| Axe Unleashed | `(0.07, 0.02, 0.53, 1.00)` |
| Young Invoker | `(0.37, 0.22, 0.67, 1.00)` |
| Hoodwink wallpaper | `(0.40, 0.05, 0.94, 0.88)` |
| Roshan Diretide 2012 | `(0.40, 0.12, 0.88, 0.91)` |
| Reptilian Refuge melee creep | `(0.21, 0.23, 0.46, 0.85)` |

QA copies/contact sheets are temporary inspection aids, not repository/runtime assets. Crop recommendations do not change the original image URLs. The later Telegram renderer must implement subject crops and inspect actual text/art layout. No final Telegram card rendering is claimed here.

## Gaps and acceptance boundary

Missing mapped entities or original sources: **none**. All 48 M1 item gaps and five chosen creep entities are covered. General unrequested inventory species remain outside selected deck scope. Unconfirmed Shadow Fiend artist set acceptance remains an explicit candidate gap but does not affect any binding.

Outstanding production step: coordinator must reconcile against final release definitions, set the actual catalog digest and approved media version, then run production media validation. `null` is intentional and must fail that final gate. No fabricated digest, final release acceptance or playable-catalog claim is made.

Fresh verification: strict UTF-8 JSON parsing; Media v1 asset fields/status/kinds/HTTPS provenance; exact 147 rule-key coverage and same-entity selected-verified matching; 168-copy manifest count; 127 selected image fetch/decode plus visual small-size inspection; diff whitespace checks. Engine tests are not applicable to these metadata-only changes; production media validation is intentionally pending digest finalization.

---

# Classic Dota v1 вЂ” M1 media source audit

Research date: 2026-10-08. Base: `902c7f52d66401e429ddd8e51441cdcd8147d101`. Scope: M1 source inventory, not M2 selections/bindings. Entity IDs follow the coordinator's canonical `hero:`, `item:`, `creep:` convention from contract update `afc773c`.

## Inventory and evidence standard

The JSON contains 168 asset records: 167 verified and 1 candidate. This asset count happens to equal the future physical deck count; it does **not** mean a complete deck's artwork. There are 123 original hero portraits, 38 original item icons, 3 promotional images, 1 wallpaper, 1 official illustration and 2 loading-screen records (one verified, one candidate). No selected manifest or bindings have been created. Assets are reusable by entity, and physical copies do not require duplicate records.

Verified means the image was visually inspected and its attributable primary publication was read. Image URLs were taken from publication image elements, CSS backgrounds or explicit links. No image URL was guessed from a search snippet. Inspection used background browser navigation/screenshots; no media was downloaded or locally prepared. Credits distinguish the publisher from individually named artists. Provenance does not itself resolve reuse rights or constitute public-release approval.

## Inspected primary publications

| Publication | Inspection and inventory outcome |
| --- | --- |
| [Valve hero gallery](https://www.dota2.com/heroes) | Read entity labels and exact CSS portrait URLs; inspected full gallery screenshot with original face crops. Recorded 123 portraits spanning class/race/monster/modifier possibilities. The default portraits are recognizable, compact landscape fallbacks. |
| [Axe hero page](https://www.dota2.com/hero/axe) | Inspected original Axe render in page and portrait URL. Gallery portrait is recorded; render itself is not a separately verified asset. |
| [Dueling Fates 7.07](https://www.dota2.com/duelingfates) | Read exact item image URLs and inspected published icons adjacent to entity names in three long screenshots from Aether Lens through Spirit Vessel. Recorded 38 icons. Historical Dota item stats were not imported into mechanics. Nullifier/Kaya URLs also appeared but were not fully inspected, so are not recorded as verified. |
| [TI2019 Battle Pass](https://www.dota2.com/international2019/battlepass/) | Read AxeExclusive and KidInvoker primary sections and exact CSS backgrounds; opened and inspected originals. Recorded Axe Unleashed and Young Invoker promos. Persona/cosmetic identity is explicit. |
| [Mistwoods](https://www.dota2.com/mistwoods?l=english) | Read original WALLPAPERS links; opened and inspected 3840Г—2160 Hoodwink wallpaper 1. Legacy item patch rendering displays unresolved placeholders here, so no icons are attributed to it. |
| [Jonathan Lee: Battletrap](https://dawndrop.artstation.com/projects/Lqxbv) | Read author's statement that this is a Clockwerk loading screen for a set currently in game. Inspected linked large 712Г—1024 original. Credits: Jonathan Lee for concept/model/illustration and Valve for character. Verified with creator's in-game statement; strong vertical composition. |
| [Matt Cristello: Murder of Souls](https://mattcristello.artstation.com/projects/1VQ1G) | Read creator and collaborator credits; inspected full page and original animated loading image. Candidate only: artist describes a set, but this primary publication does not establish Valve acceptance or in-game release. |
| [Steam Dota news archive: Diretide](https://store.steampowered.com/news/posts/?appids=570&enddate=1352228437) | Read publisher's Diretide announcement and its original full-image link. Opened HTTPS original on media.steampowered.com. Roshan dominates illustrated poster, recognizable head/wings/orange eye. Recorded official illustration; seasonal pumpkin prop must be acknowledged in later selection. Archive contains third-party news too; evidence here is the Dota team's own Diretide entry. |
| [Diretide 2020](https://www.dota2.com/diretide?l=english) | Read official page and original howtoplay-3 image URL; inspected Roshan game-model instructional composite. Recorded promo fallback. Large empty lower region and numbered bubble make it inferior to 2012 artwork. The lore-right2 image depicts a stuffed puppet; it was inspected but not selected as a recognizable creep fallback. |

Steam Community's Baby Roshan announcement was investigated, but its application content remained in a loading state; only its title and shell appeared. No asset was credited to that unresolved source. New Frontiers and modern 7.38 patch pages did not expose usable loaded content in this session. Search results for Roshan fan art and wallpaper reposts were not accepted without primary provenance. Artist portfolio discovery, Steam publisher research and original hosted images satisfy the required search beyond dota2.com.

## Accepted mapping coverage

The coordinator accepted the four class mappings while M1 was in progress. Verified original portraits cover:

| Source class | Accepted entity | Available assets |
| --- | --- | --- |
| Warrior | `hero:axe` | Original portrait and verified Axe Unleashed promo |
| Thief | `hero:riki` | Original portrait |
| Cleric | `hero:omniknight` | Original portrait |
| Wizard | `hero:crystal_maiden` | Original portrait |

Invoker, Chen, Dazzle, Oracle and other portraits remain entity inventory, not alternative class assignments.

Read-only comparison with A's 147-definition / 168-copy mapping gives 126 unique entities and 77 already covered by verified records. Every mapped hero has a portrait. All remaining gaps are items. The read snapshot still names Magic Lamp `item:relic`; coordinator has approved changing it to `item:smoke_of_deceit`, which is already covered. With that correction, coverage becomes 78 of 126 mapped entities, with 48 item gaps. This is coverage potential, not bound-definition count; bound definitions remain 0.

## Precise gaps and next step

Mapped items still requiring inspected original icons or attributable art (excluding the superseded `item:relic`):

`aegis`, `aghanims_scepter`, `assault_cuirass`, `band_of_elvenskin`, `belt_of_strength`, `black_king_bar`, `blade_mail`, `blink_dagger`, `bloodthorn`, `boots_of_bearing`, `bottle`, `broadsword`, `buckler`, `chainmail`, `cheese`, `clarity`, `crown`, `dagon`, `divine_rapier`, `enchanted_mango`, `euls_scepter`, `faerie_fire`, `hand_of_midas`, `healing_salve`, `heavens_halberd`, `helm_of_iron_will`, `helm_of_the_dominator`, `helm_of_the_overlord`, `iron_branch`, `lotus_orb`, `manta_style`, `mask_of_madness`, `moon_shard`, `orb_of_corrosion`, `phase_boots`, `platemail`, `radiance`, `ring_of_protection`, `rod_of_atos`, `sacred_relic`, `sange_and_yasha`, `scythe_of_vyse`, `shadow_amulet`, `shadow_blade`, `shivas_guard`, `talisman_of_evasion`, `town_portal_scroll`, `vanguard`.

General creep inventory has only `creep:roshan` (two verified assets). Kobolds, lane creeps, satyrs, trolls, harpies, centaurs, hellbears, ancient dragons and golems still lack inspected attributable image records. A currently maps all monster cards to heroes, so these are broader inventory gaps, not missing accepted deck mappings.

M2 must collect the missing mapped item imagery, use identical entity images for repeated copies, bind definitions only after accepted mapping integration, and pin the final exact catalog version/digest. Small-card crop checks for selected assets belong to M2; source-page visual inspection alone does not verify the final Telegram card layout. The animated Shadow Fiend candidate needs confirmed acceptance before any official-art selection.

## Verification scope

M1 verification is JSON parsing, contract-field/status/HTTPS consistency and `git diff --check`. No engine or network tests are needed for source metadata; no changing-website tests were created. Commit SHA and fresh verification output are recorded in the coordinator handoff report.
