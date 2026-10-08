# Parallel Dota Card Catalog and Complete Card Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: Use superpowers:subagent-driven-development for task execution and review, and superpowers:dispatching-parallel-agents for independent workstreams. Steps use checkbox (`- [ ]`) syntax for tracking. This plan selects parallel execution: only tasks declared independent below may run concurrently.

**Goal:** Подключить полный проверенный каталог из 168 тематических карт Dota 2 и реализовать в движке действия, необходимые для всех карт классической базовой колоды.

**Architecture:** Каталог хранится как версия JSON с отдельными определениями карт и экземплярами. Проверяемые числовые правила отделены от названий и русских описаний. Загрузчик раскрывает экземпляры в существующий `Catalog`; команды продолжают проходить через `decide`. Общие эффекты исполняются по закрытой схеме, особые правила — через явный реестр обработчиков. Неизвестный эффект или неподдерживаемое особое правило блокирует загрузку релиза.

**Tech Stack:** Python 3.12, стандартная библиотека, pytest 8; существующий пакет `dota_dungeon`. Telegram и PostgreSQL подключаются следующим отдельным планом.

**Spec:** `docs/superpowers/specs/2026-09-24-dota-munchkin-telegram-design.md`

**Existing contracts:** `docs/superpowers/implementation-notes/core-engine.md`. Базовая ветка — `main`; ядро — `c5db2e5`, последние уточнения изображений — `ba97a0c`. До исполнения зафиксировать актуальный HEAD. Метод исполнения выбран пользователем: параллельные агенты. Telegram и хранение партий остаются следующим подсистемным планом.

## Global Constraints

- Партия на 2–6 игроков. Старт: уровень 1 без выбранного героя, 4 двери и 4 сокровища.
- Каталог: ровно 168 физических экземпляров, 95 дверей и 73 сокровища. Повторы сохраняются.
- Классические эффекты, цены вещей, награды, слоты и ограничения сохраняются. Цены магазина Dota 2 не заменяют стоимость вещей «Манчкина».
- Названия и образы — герои, предметы и существа Dota 2. Русские тексты правил пишутся своими словами; исходные тексты и картинки «Манчкина» в продукт не включаются.
- Игра не получает здоровье, ману, кулдауны или другие механики матча Dota 2.
- Победный уровень 10 даёт убийство монстра или явно разрешающее исключение карты. Обычная продажа и обычная карта уровня не дают победу.
- `decide(state, command, catalog, rng) -> tuple[GameState, list[Event]]` сохраняет сигнатуру. Повтор запроса не исполняет карту второй раз.
- Один физический ID находится ровно в одной зоне. `equipped`, `role_ids` и `race_ids` — ссылки на карты в игре, а не дополнительные зоны.
- Скрытые карты направляются через `user:<id>` либо личное событие владельца. Публичное событие раскрывает только законно сыгранные или открытые карты.
- Версия и контрольная сумма каталога закрепляются за матчем. Изменение описаний или правил создаёт новую версию.
- Непроверенные цены, награды и эффекты не заменяются выдуманными значениями. Релиз каталога загружается только после проверки всех определений.

## Parallel Execution and Ownership

Одновременно работают координатор и максимум **3 исполнителя**. Названия A/B/C обозначают направления работы; для отдельной задачи создаётся свежий агент с кратким заданием и нужными файлами, без полной истории разговора. Исполнители не запускают дополнительных агентов. Проверяющий занимает освободившийся слот после окончания одной из задач.

| Направление | Владелец | Разрешённые изменения |
| --- | --- | --- |
| A — каталог | Агент каталога | `cards/data/classic-dota-v1/source-manifest.json`, `catalog.json`; `tests/test_card_manifest.py`, `tests/fixtures/classic-checklist.json`; `docs/superpowers/catalogs/classic-dota-v1-audit.md` |
| B — изображения | Агент медиа | `cards/data/classic-dota-v1/media-candidates.json`, `media.json`; `docs/superpowers/catalogs/classic-dota-v1-media-audit.md` |
| C — код | Агент движка | `src/dota_dungeon/core/*.py`; `cards/{__init__,release,schema,validation}.py`; тесты Tasks 2–6 |
| Координатор | Основной агент | Контракт, задания, журнал выполнения, `pyproject.toml`, `cards/{__main__,media}.py`, приёмочные/медиа-тесты, объединение и итоговый отчёт |

В таблице `cards/` означает `src/dota_dungeon/cards/`. Общие `model.py`, `effects.py`, `engine.py`, `combat.py` редактирует только направление C. Общие фикстуры `tests/fixtures.py` также принадлежат C; A использует собственную JSON-фикстуру. Медиа-аудит отделён от аудита правил. Изменение чужого файла сначала передаётся координатору как предложение с причиной.

### P0 — Contract and Workspaces (Coordinator)

**Files:** Create `docs/superpowers/implementation-notes/card-catalog-contract.md`, `tests/fixtures/catalog-contract-v1.json`; maintain execution ledger inside this plan's git-ignored Superpowers workspace.

- [ ] Re-read the approved spec and existing engine handoff. Run `python -m pytest -q`; record the result and base SHA in the ledger. Stop only execution of a task whose prerequisites are missing; independent tasks continue.
- [ ] Write and commit the contract: physical IDs use `<rule_key>:<copy_number>` with numbering from 1; source records are exactly Task 1's interface; the runtime JSON shape is `{version, definitions, instances}` from Task 2. Definitions carry presentation and mechanics; instances map physical IDs to definition keys. SHA-256 covers canonical UTF-8 JSON with sorted keys, compact separators and `ensure_ascii=False`, excluding an optional top-level `digest`. A declared digest must equal the computed one.
- [ ] Fix concrete JSON types for `play_phases`, `target_rule`, `restrictions`, `trigger`, `conditions`, `abilities` and effects before dispatch: enum values, required operands and optional defaults. Playable phases use the current values `turn.prepare`, `turn.after_door`, `turn.charity`, `combat.active`, `combat.run_away`; `lobby` and `game.finished` never permit normal card play. List implemented operations separately from proposed special handlers; a declared but unimplemented handler cannot pass release validation. The contract fixture contains a two-copy item, a level card and a monster, all clearly synthetic rather than verified source facts.
- [ ] Specify `media-candidates.json` as `{schema_version, assets}` keyed by `asset_id`. Each asset has `dota_entity_id`, `image_url`, `original_publication_url`, `credit`, `asset_kind`, `verified_on`, `status` (`candidate`, `verified`, `rejected`) and `notes`. Final `media.json` is `{media_version, catalog_version, catalog_digest, assets, bindings}`; `bindings` maps every definition's `rule_key` to a verified asset ID. Repeated copies share a binding. No image field changes mechanical source facts.
- [ ] Create an integration worktree/branch and separate worktrees for A/B/C through the worktree skill. All start from the same committed P0 revision. Record paths, branches and owned files in the ledger. Only the coordinator integrates commits; workers never change `main`, merge, push or reset other workspaces.

### Waves and Prerequisites

| Волна | A — каталог | B — изображения | C — код | Координатор |
| --- | --- | --- | --- | --- |
| 0 | — | — | — | P0: контракт, фикстура, рабочие деревья |
| 1 | Task 1: полный исходный манифест и соответствия Dota | M1: кандидаты артов по Dota-сущностям | Task 2: загрузчик и схема на контрактной фикстуре | Проверка отдельных результатов |
| 2 | Часть Task 7: `catalog.json`, описания и таблица покрытия правил | M2: привязки к подтверждённым соответствиям | Tasks 3 → 4 → 5 → 6, строго последовательно | Приёмочные тесты, упаковка и CLI |
| 3 | Исправления данных | Исправления источников/привязок | Исправления реализации | I1: полная проверка и интеграция |

Task 2 не ждёт фактических значений всей колоды: использует синтетический манифест из P0 для проверки схемы и сверки чисел. Полная проверка исходных правил начинается после Task 1. Tasks 3–6 используют проверенные правила и контракт после интеграции Tasks 1/2; A создаёт финальный JSON параллельно с этими задачами. M1 не ждёт соответствия каждой карты и индексирует кандидатов по Dota-сущности. M2 начинается после Task 1; окончательные `catalog_version` и `catalog_digest` записываются после готовности `catalog.json`.

Переход к следующей задаче требует принятого результата её зависимостей. Изменение контракта делает только координатор: фиксирует причину, обновляет фикстуру и сообщает всем направлениям. До такого изменения агент использует согласованную схему; неизвестные факты помечает как пробел в аудите и не подставляет приблизительные числа. Если источника конкретной карты нет, проверенный остальной набор продолжает разрабатываться, но полный релиз остаётся незавершённым.

### Review and Integration Protocol

- Для каждого задания координатор передаёт рабочий путь, базовый SHA, текст задачи, нужные ограничения спеки, контракт, разрешённые файлы и команды проверки. Готовые задания лежат в `docs/superpowers/plans/2026-10-08-card-catalog-agents/`.
- Исполнитель возвращает commit SHA, перечень файлов, команды с результатами, источники, оставшиеся пробелы и предложения изменения контракта. Код проходит цикл падающий тест → реализация → успешный тест; для исследования изображений проверяется доказательство происхождения и выбор изображения, без искусственных тестов веб-страниц.
- После задачи независимый проверяющий сверяет требования и качество в режиме чтения. Пока все три исполнителя заняты, координатор сохраняет готовый результат и запускает проверяющего после освобождения слота. Проверяющий не меняет файлы.
- Координатор объединяет принятые коммиты последовательно в интеграционной ветке, проверяет список файлов и запускает затронутые тесты. Следующий зависимый исполнитель начинает с нового принятого SHA. Решения и завершённые задачи записываются в журнал, чтобы не запускать их повторно после восстановления контекста.
- После общей проверки проводится отдельное ревью всей ветки. Затем результат интегрируется в `main` согласно ранее указанному пользователем порядку; публикация и развёртывание относятся к следующему этапу.

### M1 / M2 — Official Artwork and Bindings (Agent B)

**Files:** Create `src/dota_dungeon/cards/data/classic-dota-v1/media-candidates.json`, `media.json`, `docs/superpowers/catalogs/classic-dota-v1-media-audit.md`. Consumes the P0 media contract and Task 1's Dota mapping; produces the final media manifest consumed by I1.

- [ ] M1: collect original portraits/icons and official art, loading screens, wallpapers and promotional images. Search Steam, official channels and artists' portfolios as well as dota2.com. Record the primary publication even when a copy is hosted elsewhere; a repost alone does not prove authorship.
- [ ] M1: inspect candidates and record the depicted entity, source, credit, asset kind and verification status. Prefer a recognisable image readable on a small Telegram card. Record gaps for creeps or items without confirmed images.
- [ ] Commit candidates and media audit; report verified entity IDs and unresolved sources. Do not modify card names, rule keys or numerical mechanics.
- [ ] M2: after Task 1, bind each definition to an image of its mapped entity. An asset may serve multiple copies or cards depicting the same entity; a missing art may use that entity's verified original portrait/icon. Do not substitute an unrelated hero to fill a gap.
- [ ] After A completes `catalog.json`, write its exact version/digest into `media.json`; report the number of bound definitions and gaps. Commit `feat: map verified official Dota artwork to card definitions`.

### I1 — Whole Release Verification (Coordinator)

**Files:** Modify `pyproject.toml`; create `src/dota_dungeon/cards/__main__.py`, `src/dota_dungeon/cards/media.py`, `tests/test_card_catalog_acceptance.py`, `tests/test_card_media.py`; complete final audit summary. Consumes the code, factual manifest, playable release and media manifest. Produces `validate_media_manifest(raw: dict, release: CatalogRelease) -> None`; raises `ValueError` naming the failing key when metadata is invalid.

- [ ] Complete the CLI, wheel packaging and real-catalog scenarios from Task 7. A owns release data and rule-audit rows; the coordinator owns these code/configuration/test files.
- [ ] Add media tests `test_media_binding_covers_every_definition`, `test_media_binds_the_mapped_dota_entity`, `test_only_verified_assets_are_selected`, `test_media_is_pinned_to_catalog_digest`: assert binding keys equal release definition keys, every selected asset depicts the mapped entity, every asset has provenance/credit and verified status, and changing the catalog digest invalidates its media manifest. Tests use local metadata, not availability of remote hosts.
- [ ] Run `python -m pytest tests/test_card_media.py -q` and observe failure for the absent validator. Implement `validate_media_manifest` in `cards/media.py` with the P0 schema and have the validation CLI invoke it for the installed `media.json`. Re-run media tests; require all to pass.
- [ ] Run `python -m pytest -q`, `python -m dota_dungeon.cards validate`, and the installed-wheel smoke test from Task 7. Require all tests to pass, CLI totals 168/95/73, executable support for every rule key and a complete media audit. An unavailable art is a documented incomplete media deliverable rather than evidence that the whole stage is finished.
- [ ] Run final independent branch review; fix material findings. Integrate only the verified result and record its SHA. Report remaining Telegram/storage/timer work explicitly.

## Sources and Evidence

- Контроль состава и кратностей: [официальный список базовой колоды](https://munchkin.game/products/games/munchkin/), проверен 8 октября 2026 года.
- Приоритет правил: [официальные правила](https://munchkin.game/site-munchkin/assets/files/1138/munchkin_rules-1.pdf), [FAQ](https://munchkin.game/gameplay/faq/), [исправления](https://munchkin.game/gameplay/errata/).
- Источник каждого числа и специального условия — соответствующая оригинальная карта с поправками издателя. Для каждого определения записываются источник и дата проверки; полный текст карты не копируется в репозиторий.
- Названия героев сверяются с [официальным сайтом Dota 2](https://www.dota2.com/heroes). Названия предметов и существ фиксируются вместе с источником Valve либо ссылкой на первичный игровой материал. Изображения и их использование рассматриваются перед публичным выпуском.
- Оформление использует также официальные арты, загрузочные экраны, обои и промоматериалы. Искать их можно в Steam, официальных каналах, портфолио авторов официальных работ и на других площадках с подтверждаемым происхождением изображения. В аудите фиксируются `image_url`, `original_publication_url`, `credit` и `asset_kind`; узнаваемость и читаемость проверяются в размере Telegram-карточки.

## Review Focus

1. Карта с обязательным эффектом может попасть в стартовую руку или быть вытянута другим эффектом: триггер должен сработать, сохранив порядок раздачи, видимость и уникальность экземпляров. Проверка в Task 4.
2. Новое Dota-название не должно сломать ограничения исходной карты: сравнения выполняются по стабильным ключам правил и тегам, а не отображаемой строке. Проверка в Tasks 1, 2 и 5.
3. Удаление последнего монстра завершает бой; убийство, изгнание и избегание дают разные награды. Уже заработанные награды не выдаются до законного завершения всего боя. Проверка в Task 6.
4. Исключение равенства сил и уровень помощника могут определить победителя. Победа помощника и вынужденная помощь в победном бою должны разрешаться по классическим правилам. Проверка в Tasks 5 и 6.
5. Проклятие, потеря класса или расы и исчезновение карты, разрешающей экипировку, требуют пересчёта законности предметов без копирования, потери или автоматической смены предметов в бою. Проверка в Tasks 3 и 5.

## File Map

| Файл | Ответственность |
| --- | --- |
| `src/dota_dungeon/cards/data/classic-dota-v1/source-manifest.json` | Проверенные исходные типы, кратности, числовые значения и источники. |
| `src/dota_dungeon/cards/data/classic-dota-v1/catalog.json` | Dota-оформление, определения, экземпляры и исполнимые правила релиза. |
| `src/dota_dungeon/cards/release.py` | Версия каталога, отображение, контрольная сумма, загрузка. |
| `src/dota_dungeon/cards/schema.py` | Проверка схемы и полноты релиза. |
| `src/dota_dungeon/cards/validation.py` | Проверка соответствия исходному манифесту и поддержке движком. |
| `src/dota_dungeon/core/play.py` | Розыгрыш карт из руки и открытых вещей, цели и допустимые фазы. |
| `src/dota_dungeon/core/draw.py` | Общий механизм получения карт, обновления колод и обязательных триггеров. |
| `src/dota_dungeon/core/character.py` | Класс, раса, их способности и исключения. |
| `src/dota_dungeon/core/card_rules.py` | Явный реестр специальных правил базового каталога. |
| `tests/test_card_*.py`, `tests/test_catalog_release.py` | Правила карт, полнота каталога, скрытые события и сохранение зон. |
| `docs/superpowers/catalogs/classic-dota-v1-audit.md` | Таблица соответствий, источники правил и результаты аудита; владелец A. |
| `cards/data/classic-dota-v1/media-candidates.json`, `media.json` | Кандидаты и выбранные изображения с привязками к картам; владелец B. |
| `docs/superpowers/catalogs/classic-dota-v1-media-audit.md` | Источники, авторство и пробелы изображений; владелец B. |
| `docs/superpowers/implementation-notes/card-catalog-contract.md` | Зафиксированные интерфейсы и схема данных; владелец координатор. |

Существующие `model.py`, `catalog.py`, `effects.py`, `setup.py`, `turn.py`, `items.py`, `combat.py`, `engine.py` меняются только для подключения указанных действий. Общие изменения извлекаются в перечисленные модули, чтобы не наращивать все правила в одном файле.

---

### Task 1: Verify the Source Manifest and Dota Mapping

**Files:** Create `src/dota_dungeon/cards/data/classic-dota-v1/source-manifest.json`, `docs/superpowers/catalogs/classic-dota-v1-audit.md`; test `tests/test_card_manifest.py`.

**Interfaces:** Produces source records with `rule_key`, `source_name`, `deck`, `kind`, `copies`, `value`, `bonus`, `slots`, `size`, `treasures`, `levels`, `conditions`, `abilities`, `source_refs`, `verified_on`. `rule_key` is a stable identifier shared by all physical copies. Each audit row maps it to `dota_entity_id` and `display_name_ru`. Ability records include verified costs, limits, timing and outcome.

- [ ] Write `test_source_manifest_has_168_physical_cards` with assertions that summed copies are 168 and deck totals are 95/73; write `test_manifest_preserves_official_copy_counts`, comparing every source-name count to a separately captured official checklist, not to the production JSON itself.
- [ ] Run `python -m pytest tests/test_card_manifest.py -q`; verify failure because the manifest does not exist.
- [ ] Create the complete factual manifest and Dota mapping. Verify prices, printed bonuses, rewards and conditions from original cards and publisher corrections. Keep original card names only as audit identifiers; runtime display uses Dota names. Map the four class types to distinct heroes, including Axe for the warrior role and Riki for the thief role. Repeated copies share one definition and preserve the same mechanics.
- [ ] Publish the accepted `rule_key` → `dota_entity_id` mapping for M2. Keep artwork sources in B's media audit, separate from this task's rule evidence.
- [ ] Add `test_every_definition_has_verified_evidence` and `test_dota_names_do_not_control_mechanical_keys`: all records have evidence, positive copy counts and unique keys; changing a display name leaves the mechanical fingerprint unchanged.
- [ ] Run the manifest tests and commit `feat: verify classic card manifest and Dota mapping`.

### Task 2: Versioned Catalog Schema and Loader

**Files:** Create `src/dota_dungeon/cards/__init__.py`, `release.py`, `schema.py`, `validation.py`; modify `core/model.py`, `core/catalog.py`; test `tests/test_catalog_release.py`.

**Interfaces:** Produces frozen `CardPresentation(display_name_ru: str, description_ru: str, dota_entity_id: str, source_refs: tuple[str, ...])`, `CatalogRelease(version: str, digest: str, catalog: Catalog, presentations: dict[str, CardPresentation])`, `load_release(path: Path) -> CatalogRelease`, and `validate_release(raw: dict, manifest: dict) -> None`. Add `rule_key`, `play_phases`, `target_rule`, `restrictions` and `trigger` to `CardDef`, preserving defaults for existing tests. Add nullable `catalog_version` and `catalog_digest` to `GameState` for the service to pin.

**Parallel prerequisite:** Consume P0's contract fixture, not Task 1's unfinished manifest. Prepare an initially empty special-handler registry in `core/card_rules.py`; Task 6 extends the same registry. Introduce `CombatState.played_card_ids` here as an empty zone; Task 3 adds retention and cleanup for existing combat outcomes, Task 6 extends cleanup to its special outcomes. Only C modifies these shared model files.

- [ ] Write tests rejecting a missing physical copy, a duplicated instance ID, changed price, invalid effect operand, unknown special handler and mismatched release digest. Write a valid two-copy test in which both runtime IDs share one definition but occupy independent zones.
- [ ] Run `python -m pytest tests/test_catalog_release.py -q` and verify expected failures.
- [ ] Implement the loader for `{version, definitions, instances}`. Expand the instances into existing `CardDef` objects. Compute SHA-256 over canonical JSON using sorted keys and UTF-8. `definitions` holds presentation plus mechanics; `instances` maps a unique physical ID to its definition key. No code string is executable from data.
- [ ] Validate all numeric types without accepting booleans as integers, all target and phase enums, every nested operation and every source-manifest fingerprint. Runtime loading rejects an unsupported card rather than omitting its effect.
- [ ] Run release and existing catalog tests; commit `feat: load verified versioned card releases`.

### Task 3: Atomic Card Play and Targeted Effects

**Files:** Create `core/play.py`; modify `core/effects.py`, `core/engine.py`, `core/items.py`; test `tests/test_card_play.py`, `tests/test_card_effects.py`.

**Interfaces:** Produces `play_card(state: GameState, actor_id: int, card_id: str, target: dict, catalog: Catalog, rng: Random, now: datetime) -> tuple[GameState, list[Event]]`. Add command `play_card`; `target` identifies a player, monster or open item and never authorizes access to another hand. Extend `apply_effects` with keyword-only `choices: dict | None = None` and `rng: Random | None = None`, preserving current callers.

- [ ] Write tests for playing a normal level card at level 8, rejecting it at level 9 with the card retained, a curse aimed at another player, laying out a carried item without a bonus, and consuming a one-shot exactly once. Assert invalid target, wrong phase and repeated request preserve all zones.
- [ ] Run both new test files; verify failure for the missing command and effect selectors.
- [ ] Implement prevalidation of ownership, phase, target, choices and cost. Dispatch existing identity/equipment/combat actions where appropriate. Resolve noncombat expendable cards and discard them into their actual decks; persistent cards stay in play, combat expendables stay in `played_card_ids` until completion. Update existing win/escape cleanup and one-zone assertions in this task so retention never leaves an independently accepted stage broken. Perform the entire transition on a copy so a failed multi-effect card leaves the input intact.
- [ ] Implement selectors for worn slot, small/big item, class/race and hand-card loss. Selected hidden cards can appear only in their owner's events. Item loss cancels affected offers. Resolve conditional effects from stable keys and tags.
- [ ] Add tests for a curse with no eligible target, insufficient discard cost, chained effects where the last fails, and loss of an enabling identity card. Run the suite; commit `feat: play cards with validated targets and costs`.

### Task 4: Shared Draw Pipeline and Immediate Triggers

**Files:** Create `core/draw.py`; modify `core/setup.py`, `core/turn.py`, `core/effects.py`, `core/combat.py`; test `tests/test_card_draw.py`.

**Interfaces:** Produces `draw_cards(state: GameState, user_id: int, deck: str, count: int, face_up: bool, catalog: Catalog, rng: Random) -> tuple[GameState, list[Event]]`. Trigger handlers receive the drawn physical ID and the draw visibility; each ID is processed once per acquisition.

- [ ] Write tests for a trigger in the initial deal, a trigger during hidden room loot, a trigger during public helped rewards and a draw spanning a depleted pile. Assert one-zone ownership after every trigger and the correct audience for every additional draw.
- [ ] Run `python -m pytest tests/test_card_draw.py -q`; verify expected failures.
- [ ] Use one draw pipeline for setup, loot, rebirth, rewards and `draw` effects. When a pile empties, recycle only its own discard using the injected RNG. When both are empty, stop drawing, retain already resolved draws and emit `draw_unavailable` with the missing count; do not reject the otherwise legal action. Add tests for partially fulfilled rewards and an empty-door turn that proceeds without a drawn card. Cards whose triggers are still resolving remain outside the discard until the draw chain completes.
- [ ] Implement the obligatory level-affecting door event and the treasure trigger that draws three additional cards, including their special opening-hand ordering. The source card's required trigger determines whether it is public; a trigger does not reveal unrelated hand cards.
- [ ] Add `test_trigger_cannot_reprocess_its_discarded_instance_in_same_draw_chain`. Run draw, setup, turn and combat tests; commit `feat: resolve immediate card draws and triggers`.

### Task 5: Character Abilities and Item Exceptions

**Files:** Create `core/character.py`; modify `core/model.py`, `core/setup.py`, `core/items.py`, `core/combat.py`, `core/turn.py`, `core/engine.py`; test `tests/test_card_character.py`, `tests/test_card_equipment.py`.

**Interfaces:** Produces `use_ability(state: GameState, actor_id: int, ability_key: str, target: dict, cost_ids: list[str], catalog: Catalog, rng: Random, now: datetime) -> tuple[GameState, list[Event]]`, `effective_item_rules(state: GameState, user_id: int, catalog: Catalog) -> dict`, `effective_hand_limit(state: GameState, user_id: int, catalog: Catalog) -> int`. Add command `use_ability`; active keys are `warrior.berserk`, `thief.backstab`, `thief.steal`, `wizard.flight`, `wizard.charm`, `cleric.resurrect`, `cleric.turn_undead`, `halfling.retry_escape`. Costs and timing come from Task 1. Add nullable `Player.character_sex` with values `male`/`female` and lobby command `set_character_sex`; choose an unset value at start using injected RNG. This is a game trait for card conditions, independent of the user's profile or Dota artwork, and adds no mandatory lobby step.

- [ ] Write tests for the warrior tie exception, the elven helper's kill level, the dwarf hand/Big-item allowances, and the halfling sale/retry rules. Tests use source-rule keys even when the hero name is changed.
- [ ] Run character tests; verify that the current generic rules fail the exceptions.
- [ ] Implement the four class and three race rule sets, with discard costs and limits per combat/attempt. Persist use counters at the scope where they expire. Winning-level permissions come from the actual ability, not from an arbitrary callback flag.
- [ ] Test and implement the optional lobby trait, seed-reproducible default, conditional items/enemies and the curse changing that trait. Verify that Dota artwork and Telegram profile data never determine it.
- [ ] Write and run failing equipment tests for dual class/race enablers, item-restriction bypass attachment, a carried item that grants no bonus, and loss of the card enabling an equipped item.
- [ ] Implement the enablers and attachments without inventing physical cards. Distinguish slot usage, carrying allowance and usability restrictions. Re-evaluate bonuses after identity loss; do not allow ordinary equipment switching during combat.
- [ ] Run character, equipment, charity and trade tests; commit `feat: apply class race and equipment card exceptions`.

### Task 6: Special Combat, Rewards and Bad Stuff

**Files:** Create `core/card_rules.py`; modify `core/combat.py`, `core/effects.py`, `core/model.py`; test `tests/test_card_combat.py`, `tests/test_card_bad_stuff.py`.

**Interfaces:** Produces `SPECIAL_RULES: dict[str, Callable]` and `resolve_special_rule(state: GameState, actor_id: int, rule_key: str, target: dict, choices: dict, catalog: Catalog, rng: Random, now: datetime) -> tuple[GameState, list[Event]]`. Add `pending_rewards` to `CombatState`; each entry records monster ID, beneficiary, level/treasure entitlement and whether the outcome was a kill. Add `played_card_ids` as a physical combat zone for consumed combat cards, distinct from references in modifier lists; discard these IDs once at combat completion. Add data-backed virtual monster references for copied foes without creating a second physical card ID.

- [ ] Write tests for adding a monster with the required card, the undead joining rule, a copied monster inheriting applicable modifiers, and a monster that excludes a helper. Include an invalid multi-card play that retains both source cards.
- [ ] Run special-combat tests; verify failures for currently unsupported actions.
- [ ] Write tests that combat expendables cannot be recovered from discard during the same fight and move exactly once into their own discard when combat finishes through a special outcome. Extend Task 3's `played_card_ids` cleanup and one-zone assertions to every newly implemented completion path.
- [ ] Implement handlers for all special-combat rule keys in the verified manifest: add/copy/replace/remove monster, double strength, transfer combat, conditional enemy strength, forced-help limits, curse cancellation, chosen die result and automatic/retried escape. Prevalidate targets and costs; refresh the reaction deadline after legal intervention using the configured duration.
- [ ] Write tests for removing the last monster, killing one foe before winning the rest, fleeing after a pending reward, a helper reaching level 10, and transferring a fight with pending entitlements. Kill, removal and avoidance retain distinct rewards; no reward is duplicated.
- [ ] Implement pending entitlement settlement, immediate completion when the last foe leaves, victory precedence and each printed bad-stuff selector. Rolls and choices are independent per fighter/monster; death preserves only the allowed identity/persistent cards and uses the common draw pipeline on return.
- [ ] Run the special-combat, bad-stuff and existing combat suites; commit `feat: resolve base-deck special combat rules`.

### Task 7: Complete Playable Dota Release and Audit

**Files:** Create `src/dota_dungeon/cards/data/classic-dota-v1/catalog.json`; modify `pyproject.toml`; update audit; test `tests/test_card_catalog_acceptance.py`; create `src/dota_dungeon/cards/__main__.py`.

**Interfaces:** Produces `validate_installed_release() -> CatalogRelease` and CLI `python -m dota_dungeon.cards validate`. The successful CLI prints version, digest, 168 total, 95 Doors and 73 Treasures and exits 0. Failure names the definition and reason and exits 1.

- [ ] Write tests asserting that the shipped release loads, that each definition has a nonempty Russian rule description and Dota identity, and that every unique card has at least one named behavior test for its distinctive rule. The behavior-coverage table is keyed by manifest `rule_key`, never generated from production handlers.
- [ ] Run acceptance tests and verify failure for the missing release and coverage.
- [ ] Complete all Dota names and Russian descriptions. Show item price, bonus, slot/size and restrictions; show enemy level, rewards and bad stuff. Encode every verified effect and special handler. Do not silently use generic rules where a printed exception exists.
- [ ] Implement the validation CLI using `importlib.resources.files("dota_dungeon.cards")` to load the installed release. Configure `[tool.setuptools.package-data]` with `"dota_dungeon.cards" = ["data/**/*.json"]` so the manifest and catalog ship in built distributions.
- [ ] Add deterministic scenarios using the real catalog: two- and six-player initial deals, representative turns through normal/conditional combat, charity, sale, trade and a legal victory. Check every physical instance occupies one zone after each command; group events must not include unrelated hidden IDs.
- [ ] Run `python -m pytest -q`, `python -m dota_dungeon.cards validate`, and an isolated wheel-install smoke test. Finish the audit with sources and test names for every definition; commit `feat: ship audited 168-card Dota catalog`.

## Completion and Handoff

The catalog subsystem is complete only if every manifest definition is sourced, mapped, loadable and executable, all 168 physical instances retain their original multiplicity and mechanical values, all distinctive rules have behavior tests, the installed-package validation succeeds, and M2/I1 verify every artwork binding. Perform the execution skill's final branch review and fix material findings before integration. This document's ownership table governs Tasks 1–7: Task 7 is split between A's data and the coordinator's I1 code, rather than being given in full to both.

The following Telegram plan will connect group/private controls to the verified release and `decide`, persist games with transactions and an outbox, and schedule reaction/help/trade timeouts. Bot tokens, live groups and hosting configuration are needed only when that service is ready to connect; they do not block this catalog work.
