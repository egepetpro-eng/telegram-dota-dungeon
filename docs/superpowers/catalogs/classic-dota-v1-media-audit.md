# Classic Dota v1 — M1 media source audit

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
| [Mistwoods](https://www.dota2.com/mistwoods?l=english) | Read original WALLPAPERS links; opened and inspected 3840×2160 Hoodwink wallpaper 1. Legacy item patch rendering displays unresolved placeholders here, so no icons are attributed to it. |
| [Jonathan Lee: Battletrap](https://dawndrop.artstation.com/projects/Lqxbv) | Read author's statement that this is a Clockwerk loading screen for a set currently in game. Inspected linked large 712×1024 original. Credits: Jonathan Lee for concept/model/illustration and Valve for character. Verified with creator's in-game statement; strong vertical composition. |
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
