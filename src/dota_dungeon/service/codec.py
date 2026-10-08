"""Versioned, explicit JSON encoding of trusted model types; never pickle."""
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from random import Random
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from ..core import model
from ..core.model import GameState


MODEL_TYPES = {name: value for name, value in vars(model).items()
               if isinstance(value, type) and is_dataclass(value)
               and value.__module__ == model.__name__}


@lru_cache
def _hints(cls):
    return get_type_hints(cls)


def _validate(value, annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if annotation is Any:
        return
    if origin in (Union, UnionType):
        errors = []
        for option in args:
            try:
                _validate(value, option)
                return
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError("value does not match union: " + "; ".join(dict.fromkeys(errors)))
    if origin is Literal:
        if not any(type(value) is type(option) and value == option for option in args):
            raise ValueError("invalid literal")
        return
    if origin in (list, set, tuple, dict):
        if type(value) is not origin:
            raise ValueError("invalid container type")
        if origin is dict:
            for key, entry in value.items():
                _validate(key, args[0])
                _validate(entry, args[1])
        elif origin is tuple and args and args[-1] is not Ellipsis:
            if len(value) != len(args):
                raise ValueError("invalid tuple length")
            for entry, expected in zip(value, args):
                _validate(entry, expected)
        elif args:
            for entry in value:
                _validate(entry, args[0])
        return
    if type(value) is not annotation:
        raise ValueError("invalid value type")
    if is_dataclass(value):
        for field in fields(value):
            _validate(getattr(value, field.name), _hints(type(value))[field.name])
    if isinstance(value, datetime) and value.utcoffset() is None:
        raise ValueError("datetime requires timezone")


def encode_value(value):
    """Encode model data preserving non-string keys and tuple/set types."""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite number")
        return value
    if type(value) is datetime:
        if value.utcoffset() is None:
            raise ValueError("datetime requires timezone")
        return {"type": "datetime", "value": value.astimezone(timezone.utc).isoformat()}
    if type(value) is list:
        return [encode_value(entry) for entry in value]
    if type(value) in (tuple, set):
        items = [encode_value(entry) for entry in value]
        if type(value) is set:
            items.sort(key=lambda entry: json.dumps(entry, sort_keys=True))
        return {"type": "tuple" if type(value) is tuple else "set", "items": items}
    if type(value) is dict:
        return {"type": "map", "items": [[encode_value(key), encode_value(entry)]
                                          for key, entry in value.items()]}
    if type(value).__name__ in MODEL_TYPES and MODEL_TYPES[type(value).__name__] is type(value):
        return {"type": type(value).__name__, "fields": {
            field.name: encode_value(getattr(value, field.name)) for field in fields(value)}}
    raise ValueError("unsupported persisted value")


def decode_value(raw):
    if raw is None or type(raw) in (str, int, bool):
        return raw
    if type(raw) is float and math.isfinite(raw):
        return raw
    if type(raw) is list:
        return [decode_value(entry) for entry in raw]
    if type(raw) is not dict or type(raw.get("type")) is not str:
        raise ValueError("invalid persisted shape")
    kind = raw["type"]
    if kind == "datetime" and set(raw) == {"type", "value"}:
        try:
            result = datetime.fromisoformat(raw["value"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid datetime") from exc
        if result.utcoffset() is None:
            raise ValueError("datetime requires timezone")
        return result.astimezone(timezone.utc)
    if kind in ("tuple", "set", "map") and set(raw) == {"type", "items"}:
        if type(raw["items"]) is not list:
            raise ValueError("invalid container items")
        try:
            if kind == "map":
                result = {}
                for pair in raw["items"]:
                    if type(pair) is not list or len(pair) != 2:
                        raise ValueError("invalid mapping entry")
                    key = decode_value(pair[0])
                    if key in result:
                        raise ValueError("duplicate mapping key")
                    result[key] = decode_value(pair[1])
                return result
            items = [decode_value(entry) for entry in raw["items"]]
            return tuple(items) if kind == "tuple" else set(items)
        except TypeError as exc:
            raise ValueError("unhashable persisted value") from exc
    cls = MODEL_TYPES.get(kind)
    if cls is None or set(raw) != {"type", "fields"} or type(raw["fields"]) is not dict:
        raise ValueError("unknown persisted model")
    names = {field.name for field in fields(cls)}
    if set(raw["fields"]) - names:
        raise ValueError("unknown model fields")
    try:
        result = cls(**{name: decode_value(value) for name, value in raw["fields"].items()})
    except TypeError as exc:
        raise ValueError("missing model fields") from exc
    _validate(result, cls)
    return result


def encode_state(state: GameState) -> dict:
    _validate(state, GameState)
    return {"schema_version": 1, "state": encode_value(state)}


def _envelope(raw):
    if type(raw) is not dict or set(raw) != {"schema_version", "state"}:
        raise ValueError("invalid persistence envelope")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("unknown persistence schema")
    return decode_value(raw["state"])


def decode_state(raw: dict) -> GameState:
    result = _envelope(raw)
    _validate(result, GameState)
    return result


def encode_rng(rng: Random) -> dict:
    return {"schema_version": 1, "state": encode_value(rng.getstate())}


def decode_rng(raw: dict) -> Random:
    result = Random()
    try:
        result.setstate(_envelope(raw))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid random state") from exc
    return result
