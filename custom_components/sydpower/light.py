"""
Light platform for Sydpower BLE devices.

The device's light is a single register holding a mode: 0 off, 1 steady, 2 SOS,
3 flashing. Home Assistant models exactly this as a light with effects, so it is
one entity rather than a switch plus a separate mode select.

Mode names come from the catalog. The light's children are its modes rather than
ports, and uniquely among states their ``input_index`` is the value written to the
control register instead of a bit in the state word.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from sydpower.catalog import get_output_children

from .const import CONF_PRODUCT_KEY, DOMAIN, LIGHT_MODES, REG_LIGHT_CONTROL
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity

_LOGGER = logging.getLogger(__name__)


def _modes(product_key: str) -> list[tuple[int, str]]:
    """
    Resolve the light's modes, falling back to the hardcoded names.

    LIGHT_MODES is indexed by register value with 0 being off, so the effects are
    everything after it.
    """
    # For the light specifically, a child's index is the value written to the
    # control register rather than a state-word bit.
    modes = get_output_children(product_key, REG_LIGHT_CONTROL)
    if modes:
        return modes
    return [(value, name) for value, name in enumerate(LIGHT_MODES) if value]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sydpower light from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    modes = _modes(entry.data.get(CONF_PRODUCT_KEY) or "")
    _LOGGER.debug("Light effects: %s", [name for _value, name in modes])
    async_add_entities([SydpowerLight(coordinator, entry, modes)])


class SydpowerLight(SydpowerEntity, LightEntity):
    """The device's light, with its modes exposed as effects."""

    _attr_name = "Light"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        modes: list[tuple[int, str]],
    ) -> None:
        super().__init__(coordinator, entry, "light")
        self._modes = modes
        self._by_name = {name: value for value, name in modes}
        self._by_value = {value: name for value, name in modes}
        self._attr_effect_list = [name for _value, name in modes]
        # Steady on is the lowest non-zero mode; used when turned on without an
        # effect, so a plain toggle does not start the light flashing.
        self._default_value = modes[0][0] if modes else 1

    @property
    def available(self) -> bool:
        return super().available and self._holding(REG_LIGHT_CONTROL) is not None

    @property
    def is_on(self) -> bool | None:
        value = self._holding(REG_LIGHT_CONTROL)
        return None if value is None else value != 0

    @property
    def effect(self) -> str | None:
        """The active mode, or None when off or holding an unmapped value."""
        value = self._holding(REG_LIGHT_CONTROL)
        if not value:
            return None
        return self._by_value.get(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, honouring a requested effect and otherwise going steady."""
        effect = kwargs.get(ATTR_EFFECT)
        if effect is not None and effect not in self._by_name:
            # Raising would be noisier than falling back, and Home Assistant
            # validates against effect_list before reaching here anyway.
            _LOGGER.warning("Unknown light effect %r; using steady on", effect)
            effect = None

        value = self._by_name[effect] if effect else self._default_value
        if self._holding(REG_LIGHT_CONTROL) == value:
            return
        await self.coordinator.async_write_register(REG_LIGHT_CONTROL, value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._holding(REG_LIGHT_CONTROL) == 0:
            return
        await self.coordinator.async_write_register(REG_LIGHT_CONTROL, 0)
