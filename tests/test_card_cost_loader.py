"""Cost policy schema must validate before rejecting an unimplemented ability."""

import pytest

from test_catalog_release import fixture_pair, mutate_mechanic, validate


def ability(mode, zone='hand'):
    return {'key': 'unimplemented-synthetic', 'cost': {'zone': zone, 'count': 3, 'mode': mode},
            'limit': {'scope': 'combat', 'max_uses': 1}, 'phases': ['combat.active']}


@pytest.mark.parametrize('mode', ['exact', 'all_hand'])
def test_valid_cost_mode_still_requires_real_handler(mode):
    raw, manifest = fixture_pair()
    mutate_mechanic(raw, manifest, 'abilities', [ability(mode)])
    with pytest.raises(ValueError, match='unknown or unimplemented rule'):
        validate(raw, manifest)


def test_all_hand_requires_hand_zone_before_handler_resolution():
    raw, manifest = fixture_pair()
    mutate_mechanic(raw, manifest, 'abilities', [ability('all_hand', 'either')])
    with pytest.raises(ValueError, match='all_hand requires hand'):
        validate(raw, manifest)


def test_unknown_cost_mode_rejected_before_handler_resolution():
    raw, manifest = fixture_pair()
    mutate_mechanic(raw, manifest, 'abilities', [ability('at_least')])
    with pytest.raises(ValueError, match='cost.mode: invalid'):
        validate(raw, manifest)
