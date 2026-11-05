"""Guard that every entity class has opted in to in-place entity_id renames.

From Home Assistant 2026.11, renaming an entity_id updates the entity in place
instead of removing and re-adding it. A custom integration's class that defines
its own add or remove hook keeps the old remove-and-re-add path unless it, or a
subclass of it, also defines async_entity_id_changed. That fallback is due to be
removed in 2027.11, so this test fails as soon as a class needs the hook and
lacks it -- for example if a sensor later grows async_will_remove_from_hass.
"""

import inspect

import pytest

from custom_components.rclone import binary_sensor, sensor, switch
from homeassistant.helpers.entity import Entity

try:
    from homeassistant.helpers.entity import _entity_class_requires_readd  # type: ignore[attr-defined]
except ImportError:  # Home Assistant before 2026.11

    def _entity_class_requires_readd(entity_class: type[Entity]) -> bool:
        """Port of the 2026.11.0 check in homeassistant/helpers/entity.py."""
        methods = (
            "async_prepare_to_add_to_hass",
            "async_added_to_hass",
            "async_will_remove_from_hass",
        )
        mro = [
            cls
            for cls in entity_class.__mro__
            if not cls.__module__.startswith("homeassistant.")
        ]
        owners = [cls for cls in mro if "async_entity_id_changed" in cls.__dict__]
        return any(
            any(method in cls.__dict__ for method in methods)
            and not any(issubclass(owner, cls) for owner in owners)
            for cls in mro
        )


ENTITY_CLASSES = [
    cls
    for module in (binary_sensor, sensor, switch)
    for _, cls in inspect.getmembers(module, inspect.isclass)
    if issubclass(cls, Entity) and cls.__module__ == module.__name__
]


def test_entity_classes_were_found() -> None:
    """The table below is not silently empty."""
    assert sensor.LastSuccessSensor in ENTITY_CLASSES
    assert len(ENTITY_CLASSES) >= 3


@pytest.mark.parametrize("entity_class", ENTITY_CLASSES, ids=lambda c: c.__name__)
def test_entity_id_change_happens_in_place(entity_class: type[Entity]) -> None:
    """No class falls back to remove-and-re-add on an entity_id rename."""
    assert not _entity_class_requires_readd(entity_class)
