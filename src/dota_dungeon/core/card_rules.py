"""Implemented rule capabilities, registered by code rather than card data.

Special, condition and trigger validators receive their descriptor's ``args``.
Ability validators receive its complete cost/limit/phases descriptor (without
``key``), so the implemented ability can constrain its usage policy.
"""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RegisteredRule:
    handler: Callable[..., Any]
    validate_args: Callable[[dict[str, Any]], None]


SPECIAL_HANDLERS: dict[str, RegisteredRule] = {}
CONDITION_HANDLERS: dict[str, RegisteredRule] = {}
TRIGGER_HANDLERS: dict[str, RegisteredRule] = {}
ABILITY_HANDLERS: dict[str, RegisteredRule] = {}
SPECIAL_RULES = SPECIAL_HANDLERS

# Import code-owned builtins so release validation sees real implementations.
from .draw_triggers import (  # noqa: E402
    all_clerics_gain_level, hoard, mandatory_play,
    _cleric_args, _hoard_args, _mandatory_args,
)

TRIGGER_HANDLERS.update({
    "mandatory_play": RegisteredRule(mandatory_play, _mandatory_args),
    "hoard": RegisteredRule(hoard, _hoard_args),
})
SPECIAL_HANDLERS["all_clerics_gain_level"] = RegisteredRule(
    all_clerics_gain_level, _cleric_args)

from .character_rules import register as _register_character

_register_character(
    RegisteredRule, SPECIAL_HANDLERS, CONDITION_HANDLERS, ABILITY_HANDLERS
)
