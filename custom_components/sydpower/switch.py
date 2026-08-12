"""
Switch platform for Sydpower BLE devices.

Switches are derived from the product catalog: every state carrying a control
register is a togglable output, so this works for any product in the catalog rather
than only the device it was developed against.

The light is excluded. Its register holds a mode rather than a boolean, so it is a
light entity with effects — see light.py.

Two controls are added on top of the catalog, which describes them for no product.
The app hardcodes them just as it hardcodes the charge and discharge thresholds, so
being absent from the catalog does not mean absent from the device — it means the
catalog is not the whole story. Both were traced in the app rather than inherited
on trust: register 56 is written by a toggle on the setting page labelled
device.key-sound, and register 57 is bound as a form control over the holding bank
labelled device.silent-charging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from sydpower.catalog import get_product_states
from sydpower.constants import WRITABLE_HOLDING_REGISTERS

from .const import (
    CONF_PRODUCT_KEY,
    DOMAIN,
    REG_AC_SILENT_CONTROL,
    REG_KEY_SOUND,
    REG_LIGHT_CONTROL,
)
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SydpowerSwitchDescription(SwitchEntityDescription):
    """Describes a switch backed by a single holding register."""

    register: int


# Controls the app hardcodes and the catalog omits. Keyed by register, since there
# is no catalog entry to key on.
EXTRA_SWITCHES: tuple[tuple[int, str], ...] = (
    (REG_KEY_SOUND, "Key sound"),
    (REG_AC_SILENT_CONTROL, "AC silent charging"),
)


def _descriptions(product_key: str) -> list[SydpowerSwitchDescription]:
    """Build a switch per catalog output, plus the app's hardcoded extras."""
    descriptions: list[SydpowerSwitchDescription] = []

    for state in get_product_states(product_key):
        register = state.get("holding_index")
        if register is None:
            continue  # a port, not something controllable
        if register == REG_LIGHT_CONTROL:
            continue  # multi-valued; handled by the light platform
        if register not in WRITABLE_HOLDING_REGISTERS:
            # The library would refuse the write, so do not offer a control that
            # cannot work.
            _LOGGER.debug(
                "Skipping catalog output %r: register %d is not writable",
                state.get("function_name"),
                register,
            )
            continue

        descriptions.append(
            SydpowerSwitchDescription(
                # The catalog's own identifier: stable across refreshes and unique
                # per product. Entity ids are slugified from the device and entity
                # names, so this only has to be stable, not readable.
                key=state["id"],
                name=state.get("function_name") or f"Register {register}",
                register=register,
                device_class=SwitchDeviceClass.OUTLET,
            )
        )

    known = {d.register for d in descriptions}
    for register, name in EXTRA_SWITCHES:
        # Skip if the catalog ever starts describing one of these, so the same
        # control is never offered twice.
        if register in known or register not in WRITABLE_HOLDING_REGISTERS:
            continue
        descriptions.append(
            SydpowerSwitchDescription(
                key=f"register_{register}",
                name=name,
                register=register,
                # Not an outlet: these configure the unit rather than switch power.
                device_class=SwitchDeviceClass.SWITCH,
                entity_category=EntityCategory.CONFIG,
            )
        )

    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower switches from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    product_key = entry.data.get(CONF_PRODUCT_KEY) or ""

    descriptions = _descriptions(product_key)
    if not descriptions:
        _LOGGER.warning(
            "No switches for %r: the catalog describes no controllable outputs "
            "for this product",
            product_key,
        )
    async_add_entities(
        SydpowerSwitch(coordinator, entry, desc) for desc in descriptions
    )


class SydpowerSwitch(SydpowerEntity, SwitchEntity):
    """A switch writing 0 or 1 to one holding register."""

    entity_description: SydpowerSwitchDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerSwitchDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Unavailable until the register has actually been read."""
        return (
            super().available
            and self._holding(self.entity_description.register) is not None
        )

    @property
    def is_on(self) -> bool | None:
        # Non-zero rather than == 1: these are booleans in practice, but treating
        # any non-zero value as on avoids reporting "off" for an unexpected value.
        value = self._holding(self.entity_description.register)
        return None if value is None else value != 0

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._write(1)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._write(0)

    async def _write(self, value: int) -> None:
        """Write unless the device already reports the requested state."""
        # Skipping redundant writes matters here: each one costs a full BLE
        # connect/disconnect cycle.
        if self._holding(self.entity_description.register) == value:
            _LOGGER.debug(
                "Skipping %s write; register %d already reads %d",
                self.entity_id,
                self.entity_description.register,
                value,
            )
            return
        await self.coordinator.async_write_register(
            self.entity_description.register, value
        )
