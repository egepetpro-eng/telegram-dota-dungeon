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
