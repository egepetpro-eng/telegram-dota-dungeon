"""Validate packaged production resources before creating any public game."""
from importlib.resources import as_file, files
import json
import re

from .release import load_release
from .media import validate_media


def _directory(version):
    if type(version) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", version):
        raise ValueError("invalid catalog version")
    return files("dota_dungeon.cards").joinpath("data", version)


def validate_installed_release(version="classic-dota-v1"):
    with as_file(_directory(version)) as folder:
        release = load_release(folder / "catalog.json")
    totals = {deck: sum(card.deck == deck for card in release.catalog.values()) for deck in ("door", "treasure")}
    if len(release.catalog) != 168 or totals != {"door": 95, "treasure": 73}:
        raise ValueError("production release requires 168 cards, 95 Doors and 73 Treasures")
    return release


def load_installed_media(release):
    raw = json.loads(_directory(release.version).joinpath("media.json").read_text(encoding="utf-8"))
    return validate_media(raw, release)
