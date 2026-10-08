"""Only complete, reviewed artwork bindings for this exact release may ship."""
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit


@dataclass(frozen=True)
class MediaRelease:
    media_version: str
    catalog_digest: str
    images: dict[str, str]

    def image_for(self, card_id: str) -> str | None:
        return self.images.get(card_id)


def _url(value):
    if type(value) is not str:
        raise ValueError("media URL must be text")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("media URL must be public HTTPS")


def validate_media(raw, release) -> MediaRelease:
    if type(raw) is not dict or set(raw) != {"media_version", "catalog_version", "catalog_digest", "assets", "bindings"}:
        raise ValueError("invalid media manifest structure")
    version = raw["media_version"]
    if type(version) is not str or not version or "draft" in version.lower():
        raise ValueError("media release is incomplete")
    if raw["catalog_version"] != release.version or raw["catalog_digest"] != release.digest:
        raise ValueError("media is not pinned to the catalog")
    assets, bindings = raw["assets"], raw["bindings"]
    if type(assets) is not dict or type(bindings) is not dict:
        raise ValueError("invalid media assets/bindings")
    definitions = {card.rule_key for card in release.catalog.values()}
    if set(bindings) != definitions:
        raise ValueError("media bindings do not cover exact catalog definitions")
    images = {}
    for card_id, card in release.catalog.items():
        asset_id = bindings[card.rule_key]
        if type(asset_id) is not str or asset_id not in assets:
            raise ValueError(f"{card.rule_key}: unknown media asset")
        asset = assets[asset_id]
        required = {"dota_entity_id", "image_url", "original_publication_url", "credit", "asset_kind", "verified_on", "status", "notes"}
        if type(asset) is not dict or set(asset) != required:
            raise ValueError(f"{card.rule_key}: invalid asset metadata")
        if asset["status"] != "verified" or asset["dota_entity_id"] != release.presentations[card_id].dota_entity_id:
            raise ValueError(f"{card.rule_key}: artwork is unverified or another entity")
        if asset["asset_kind"] not in {"portrait", "icon", "promo", "loading_screen", "art", "official_art", "wallpaper"}:
            raise ValueError(f"{card.rule_key}: invalid artwork kind")
        if type(asset["credit"]) is not str or not asset["credit"].strip():
            raise ValueError(f"{card.rule_key}: artwork credit missing")
        if type(asset["notes"]) is not str:
            raise ValueError(f"{card.rule_key}: invalid artwork notes")
        try:
            verified = date.fromisoformat(asset["verified_on"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{card.rule_key}: invalid artwork verification date") from error
        if verified.isoformat() != asset["verified_on"]:
            raise ValueError(f"{card.rule_key}: invalid artwork verification date")
        _url(asset["image_url"])
        _url(asset["original_publication_url"])
        images[card_id] = asset["image_url"]
    return MediaRelease(version, release.digest, images)
