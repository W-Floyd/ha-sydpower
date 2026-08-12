"""
Datetime platform for Sydpower BLE devices: when charging is scheduled to start.

The device stores a *delay* in minutes, not a time, and counts it down. So this
entity is a view over that countdown rather than stored state of its own:

* Reading it: the countdown in input 57, projected forward from now. Zero means
  nothing is scheduled, and the value is ``None``.
* Setting it: the delay to the requested time is computed and written to holding
  63, which is what the app does.
* Expiry: nothing to do. Once the device's countdown reaches zero the projection
  yields ``None`` and the entity clears itself. A schedule set from the app appears
  here for the same reason.

The schedule is one-shot; the device has no notion of repeating. Re-arming daily is
an automation's job, which this entity exists to make possible.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from sydpower.constants import WRITABLE_HOLDING_REGISTERS

from .const import (
    DOMAIN,
    INPUT_SCHEDULED_CHARGE_COUNTDOWN,
    REG_SCHEDULED_CHARGE,
)
from .coordinator import SydpowerCoordinator
from .entity import SydpowerEntity

_LOGGER = logging.getLogger(__name__)

# Writing zero cancels, so a schedule needs at least one minute. The ceiling comes
# from the allowlist rather than being repeated here.
MIN_DELAY_MINUTES = 1


def _max_delay_minutes() -> int:
    return WRITABLE_HOLDING_REGISTERS[REG_SCHEDULED_CHARGE][1]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the scheduled charge datetime from a config entry."""
    coordinator: SydpowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    if REG_SCHEDULED_CHARGE not in WRITABLE_HOLDING_REGISTERS:
        return
    async_add_entities([SydpowerScheduledCharge(coordinator, entry)])


class SydpowerScheduledCharge(SydpowerEntity, DateTimeEntity):
    """When charging is scheduled to start, or None when nothing is scheduled."""

    _attr_name = "Scheduled charge"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "scheduled_charge")
        # The projection moves with the clock, so it is held steady while it agrees
        # with the countdown; see native_value.
        self._reported: datetime | None = None

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._input(INPUT_SCHEDULED_CHARGE_COUNTDOWN) is not None
        )

    @property
    def native_value(self) -> datetime | None:
        """
        Project the device's countdown into a wall-clock time.

        The projection would otherwise shift by a few seconds on every poll, since
        the countdown has minute resolution while "now" does not, producing a state
        change every poll and a great deal of noise. The previously reported value
        is therefore kept whenever it still agrees with the countdown to within a
        minute.
        """
        countdown = self._input(INPUT_SCHEDULED_CHARGE_COUNTDOWN)
        if countdown is None or countdown <= 0:
            self._reported = None
            return None

        projected = dt_util.utcnow() + timedelta(minutes=countdown)
        projected = projected.replace(second=0, microsecond=0)

        if (
            self._reported is not None
            and abs((projected - self._reported).total_seconds()) <= 60
        ):
            return self._reported

        self._reported = projected
        return projected

    async def async_set_value(self, value: datetime) -> None:
        """Schedule charging for *value*, rejecting anything out of range."""
        now = dt_util.utcnow()
        target = dt_util.as_utc(value)
        maximum = _max_delay_minutes()

        # Round rather than truncate: a target 90 seconds away is better honoured
        # as two minutes than as one.
        delay = round((target - now).total_seconds() / 60)

        if delay < MIN_DELAY_MINUTES:
            raise ServiceValidationError(
                f"{value.isoformat()} is not at least {MIN_DELAY_MINUTES} minute(s) "
                f"in the future; use the cancel button to clear a schedule"
            )
        if delay > maximum:
            raise ServiceValidationError(
                f"{value.isoformat()} is {delay} minutes away, and the device only "
                f"schedules up to {maximum} minutes ({maximum // 60} hours) ahead"
            )

        _LOGGER.debug(
            "Scheduling charge for %s, a delay of %d minute(s)", target, delay
        )
        await self.coordinator.async_write_register(REG_SCHEDULED_CHARGE, delay)
        # Report the requested time rather than re-deriving it, so the value does
        # not appear to jump by a minute immediately after being set.
        self._reported = target.replace(second=0, microsecond=0)
