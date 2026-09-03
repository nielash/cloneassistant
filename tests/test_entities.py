"""Tests for entity naming."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

HEALTH = "binary_sensor.bisync_health"
JOB_SWITCH = "switch.bisync"


async def test_entity_ids_are_prefixed_with_the_device(
    hass: HomeAssistant, setup_integration
) -> None:
    """has_entity_name composes "<device> <role>" instead of a bare role.

    Without it a second job produced binary_sensor.health_2, and there was no
    way to tell from the entity id which job it belonged to.
    """
    await setup_integration()

    registry = er.async_get(hass)
    for entity_id in (HEALTH, JOB_SWITCH):
        assert registry.async_get(entity_id) is not None, f"missing {entity_id}"

    # The role is the entity's own name; the device supplies the rest.
    assert registry.async_get(HEALTH).original_name == "Health"
    assert hass.states.get(HEALTH).attributes["friendly_name"] == "Bisync Health"

    # The switch is the job itself, so it takes the device name outright.
    assert registry.async_get(JOB_SWITCH).original_name is None
    assert hass.states.get(JOB_SWITCH).attributes["friendly_name"] == "Bisync"


async def test_unique_ids_are_unchanged(
    hass: HomeAssistant, setup_integration
) -> None:
    """Renaming must not orphan the entities of an existing install."""
    await setup_integration()

    registry = er.async_get(hass)
    assert registry.async_get(HEALTH).unique_id == "rclone-bisync_Health"
    assert registry.async_get(JOB_SWITCH).unique_id == "rclone-bisync_Bisync"
