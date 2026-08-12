"""
Select platform for Sydpower BLE devices.

Most selects are built from the product catalog rather than hardcoded: it supplies
each setting's register, its option list and its unit, per product, so this works
across the whole catalog rather than only the device it was developed against.

What the catalog does *not* describe is how an option is stored in its register.
The app applies rules keyed by register number — raw value, one-based index, or
value multiplied by 60 — and those live in the library's ``SETTING_ENCODINGS``.
Applying the wrong one writes a plausible but incorrect value to a persisted
settings register, so the encoding is looked up explicitly rather than assumed.

The light is not here. It holds a mode rather than one of a list of settings, so
it is a light entity with its modes as effects — see light.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from sydpower.catalog import (
    PANEL_VERSION_REGISTER,
    gated_setting_options,
    get_product_settings,
)
from sydpower.constants import (
    SETTING_ENCODING_INDEX1,
    SETTING_ENCODING_X60,
    WRITABLE_HOLDING_REGISTERS,
    setting_encoding,
)

from .const import CONF_NAME, CONF_PRODUCT_KEY, DOMAIN
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SydpowerSelectDescription(SelectEntityDescription):
    """Describes a select backed by one holding register."""

    register: int
    # Raw register values, index-aligned with the option labels.
    values: tuple[int, ...]
    choices: tuple[str, ...]


def _label(value: int, index: int, units: list[str], data_list: list[int]) -> str:
    """
    Render one option's label.

    ``units`` is overloaded in the catalog: as many entries as options means they
    are per-option labels; otherwise entry 0 is a unit shared by all of them.
    """
    if len(units) == len(data_list) and units[index]:
        return units[index]
    unit = units[0] if units else ""
    return f"{value} {unit}".strip()


def _encode(register: int, value: int, index: int) -> int:
    """Convert an option into the value its register actually stores."""
    encoding = setting_encoding(register)
    if encoding == SETTING_ENCODING_INDEX1:
        return index + 1
    if encoding == SETTING_ENCODING_X60:
        return value * 60
    return value


def _catalog_descriptions(
    product_key: str,
    product_name: str,
    panel_version: int | None,
) -> list[SydpowerSelectDescription]:
    """Build a select description per catalog setting that offers a choice."""
    descriptions: list[SydpowerSelectDescription] = []

    for setting in get_product_settings(product_key):
        register = setting.get("holding_index")
        # Some options cannot be honoured on particular product and panel-version
        # combinations, and the app hides them. Without an authenticated gate
        # table this is a no-op.
        options = gated_setting_options(setting, product_name, panel_version)
        # A bit-packed setting addresses part of a register, which this platform
        # does not implement; skip rather than write a whole register.
        if register is None or len(options) < 2 or "bit" in setting:
            continue
        if register not in WRITABLE_HOLDING_REGISTERS:
            # The library would reject the write anyway; skip it here so no
            # entity is offered that cannot work.
            _LOGGER.debug(
                "Skipping catalog setting %r: register %s is not writable",
                setting.get("function_name"),
                register,
            )
            continue

        units = setting.get("units") or []
        # Labels come from the unfiltered list so a gated option does not shift
        # the remaining labels.
        full = setting.get("data_list") or options
        values = tuple(_encode(register, v, full.index(v)) for v in options)
        low, high = WRITABLE_HOLDING_REGISTERS[register]
        if any(not low <= v <= high for v in values):
            # A mismatch means the encoding table and the allowlist disagree,
            # which is a bug here rather than a device fault. Skip loudly.
            _LOGGER.warning(
                "Skipping catalog setting %r: encoded values %s fall outside the "
                "permitted range %s for register %d",
                setting.get("function_name"),
                values,
                (low, high),
                register,
            )
            continue

        name = setting.get("function_name") or f"Register {register}"
        descriptions.append(
            SydpowerSelectDescription(
                key=f"setting_{register}",
                name=name,
                register=register,
                values=values,
                choices=tuple(_label(v, full.index(v), units, full) for v in options),
                entity_category=EntityCategory.CONFIG,
            )
        )

    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sydpower select entities from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    product_key = entry.data.get(CONF_PRODUCT_KEY) or ""

    # The panel version is only known once a poll has happened; when it is not
    # yet available the gate simply does not apply.
    data = coordinator.data
    panel_version = (
        data.holding[PANEL_VERSION_REGISTER]
        if data is not None and PANEL_VERSION_REGISTER < len(data.holding)
        else None
    )
    descriptions = _catalog_descriptions(
        product_key, entry.data.get(CONF_NAME, ""), panel_version
    )
    _LOGGER.debug("Adding %d select(s) for %s", len(descriptions), product_key)
    async_add_entities(
        SydpowerSelect(coordinator, entry, desc) for desc in descriptions
    )


class SydpowerSelect(SydpowerEntity, SelectEntity):
    """A select mapping option labels onto raw holding-register values."""

    entity_description: SydpowerSelectDescription

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
        description: SydpowerSelectDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description
        self._attr_options = list(description.choices)

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    @property
    def current_option(self) -> str | None:
        """Map the raw register value back to a label, or None if unrecognised."""
        value = self._holding(self.entity_description.register)
        if value is None:
            return None
        try:
            index = self.entity_description.values.index(value)
        except ValueError:
            # An unexpected value means the encoding is wrong for this model;
            # reporting unknown is safer than showing a misleading option.
            return None
        return self.entity_description.choices[index]

    async def async_select_option(self, option: str) -> None:
        description = self.entity_description
        index = description.choices.index(option)
        await self.coordinator.async_write_register(
            description.register, description.values[index]
        )
