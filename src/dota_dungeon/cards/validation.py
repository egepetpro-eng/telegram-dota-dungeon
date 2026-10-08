"""Validate every physical copy and source fact before creating runtime cards."""

from datetime import date
import hashlib
import json

from .schema import (
    MECHANIC_KEYS, integer, object_fields, sequence, strings, text,
    validate_mechanics, validate_presentation,
)


SOURCE_METADATA = {
    "rule_key", "copies", "source_name", "source_refs", "verified_on",
    "dota_entity_id", "display_name_ru", "evidence_status", "evidence_notes",
}


def canonical_digest(raw: dict) -> str:
    """Hash the complete release payload except its optional declared digest."""
    payload = {key: value for key, value in raw.items() if key != "digest"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_release(raw: dict, manifest: dict) -> None:
    object_fields(raw, {"version", "definitions", "instances", "digest"},
                  {"version", "definitions", "instances"}, "release")
    object_fields(manifest, {"version", "cards"}, {"version", "cards"}, "source manifest")
    text(raw["version"], "release.version")
    text(manifest["version"], "source manifest.version")
    if raw["version"] != manifest["version"]:
        raise ValueError("release version does not match source manifest version")
    definitions = raw["definitions"]
    instances = raw["instances"]
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError("release.definitions: expected nonempty object")
    if not isinstance(instances, dict):
        raise ValueError("release.instances: expected object")
    records = sequence(manifest["cards"], "source manifest.cards")
    if not records:
        raise ValueError("source manifest.cards: expected nonempty list")
    source_mechanics = {}
    expected_instances = {}
    for index, record in enumerate(records):
        path = f"source manifest.cards[{index}]"
        object_fields(record, SOURCE_METADATA | MECHANIC_KEYS,
                      (SOURCE_METADATA - {"evidence_notes"}) | {"deck", "kind"}, path)
        key = record["rule_key"]
        text(key, f"{path}.rule_key")
        if key in source_mechanics:
            raise ValueError(f"{path}: duplicate source rule_key {key!r}")
        if record["evidence_status"] != "verified":
            raise ValueError(f"{path}: evidence_status must be verified")
        integer(record["copies"], f"{path}.copies", 1)
        for field in ("source_name", "dota_entity_id", "display_name_ru", "verified_on"):
            text(record[field], f"{path}.{field}")
        if "evidence_notes" in record and not isinstance(record["evidence_notes"], str):
            raise ValueError(f"{path}.evidence_notes: expected string")
        strings(record["source_refs"], f"{path}.source_refs", nonempty=True)
        try:
            verified_on = date.fromisoformat(record["verified_on"])
        except ValueError as error:
            raise ValueError(f"{path}.verified_on: expected valid YYYY-MM-DD") from error
        if verified_on.isoformat() != record["verified_on"]:
            raise ValueError(f"{path}.verified_on: expected YYYY-MM-DD")
        source_mechanics[key] = validate_mechanics(
            {field: value for field, value in record.items() if field in MECHANIC_KEYS}, path)
        expected_instances.update({f"{key}:{copy}": key for copy in range(1, record["copies"] + 1)})
    for key in definitions:
        text(key, "release definition key")
    if set(definitions) != set(source_mechanics):
        raise ValueError("release definitions do not match source manifest rule keys")
    for key, definition in definitions.items():
        path = f"release.definitions.{key}"
        object_fields(definition, {"presentation", "mechanics"}, {"presentation", "mechanics"}, path)
        validate_presentation(definition["presentation"], f"{path}.presentation")
        mechanics = validate_mechanics(definition["mechanics"], f"{path}.mechanics")
        if mechanics != source_mechanics[key]:
            raise ValueError(f"{path}: mechanics do not match verified source facts")
    for card_id, key in instances.items():
        text(card_id, "release instance id")
        text(key, f"release.instances.{card_id}")
    if instances != expected_instances:
        raise ValueError("release instances do not match source copies and physical copy numbering")
    digest = canonical_digest(raw)
    if "digest" in raw and raw["digest"] != digest:
        raise ValueError("release digest does not match canonical SHA-256")
