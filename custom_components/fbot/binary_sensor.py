"""Binary sensor platform for the Fbot integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    KEY_BATTERY_S1_CONNECTED,
    KEY_BATTERY_S2_CONNECTED,
    translate,
)
from .coordinator import FbotCoordinator
from .product_catalog import FEATURES


def _device_info(coordinator: FbotCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.address)},
        name=coordinator._device_name or "Fbot Device",
        manufacturer="BrightEMS / Sydpower",
        model=coordinator.profile.device_type,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FbotCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []

    # --- Connectivity sensor (always present) ---
    entities.append(FbotConnectivitySensor(coordinator))

    # --- Hardcoded satellite-battery sensors (PPS only) ---
    if coordinator.profile.device_type in ("pps", "pps_v1"):
        entities.append(
            FbotDataKeyBinarySensor(
                coordinator,
                key="battery_s1_connected",
                name="Battery S1 Connected",
                data_key=KEY_BATTERY_S1_CONNECTED,
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            )
        )
        entities.append(
            FbotDataKeyBinarySensor(
                coordinator,
                key="battery_s2_connected",
                name="Battery S2 Connected",
                data_key=KEY_BATTERY_S2_CONNECTED,
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            )
        )

    # --- Catalog-driven children sensors ---
    # Each parent state can have zero or more children. A child represents
    # an individual sub-output (e.g. a specific USB port or LED mode) and
    # reports whether that sub-output is currently active (register != 0).
    features = FEATURES.get(coordinator.profile.product_id, {"states": [], "settings": []})
    for state in features["states"]:
        parent_name = translate(state["function_name"])
        for child in state.get("children", []):
            child_name = translate(child["function_name"])
            entities.append(
                FbotChildBinarySensor(
                    coordinator,
                    parent_name=parent_name,
                    child=child,
                    child_name=child_name,
                )
            )

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class FbotConnectivitySensor(CoordinatorEntity[FbotCoordinator], BinarySensorEntity):
    """Tracks whether the BLE connection to the Fbot device is active."""

    _attr_has_entity_name = True
    _attr_name = "Connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_available = True

    def __init__(self, coordinator: FbotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_connected"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_connected


class FbotDataKeyBinarySensor(CoordinatorEntity[FbotCoordinator], BinarySensorEntity):
    """A binary sensor backed by a named key in coordinator.data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FbotCoordinator,
        *,
        key: str,
        name: str,
        data_key: str,
        device_class: BinarySensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._data_key = data_key
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        return super().available and self._data_key in (self.coordinator.data or {})

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self._data_key)


class FbotChildBinarySensor(CoordinatorEntity[FbotCoordinator], BinarySensorEntity):
    """Reports whether a catalog child sub-output is active.

    Children belong to a parent state and each map to a distinct input register
    (i_{input_index}). A non-zero register value means the sub-output is on.

    Entity name format: "{Parent Name} {Child Name}"
    e.g. "USB Output QC3.0", "DC Output Vehicle Charging"
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FbotCoordinator,
        *,
        parent_name: str,
        child: dict,
        child_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._data_key = f"i_{child['input_index']}"
        self._attr_name = f"{parent_name} {child_name}"
        self._attr_unique_id = f"{coordinator.address}_child_{child['id']}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        return super().available and self._data_key in (self.coordinator.data or {})

    @property
    def is_on(self) -> bool | None:
        val = (self.coordinator.data or {}).get(self._data_key)
        if val is None:
            return None
        return bool(val)
