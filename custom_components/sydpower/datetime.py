"""
Datetime platform for Sydpower BLE devices: when charging is scheduled to start.

The device stores a *delay* in minutes and counts it down, so a wall-clock time has
to be reconstructed. Deriving it from the countdown on every poll would make the
value drift by seconds each time, because the countdown has minute resolution while
"now" does not — a state change every poll for a time that has not actually moved.

So the target time set here is remembered, reported verbatim, and merely *checked*
against the countdown:

* Setting it stores the requested time and writes the delay to holding 63.
* Reading it returns the stored time unchanged, as long as the countdown still
  agrees within a tolerance. The value therefore never drifts.
* If the countdown disagrees, the schedule was changed elsewhere — from the app, or
  cancelled — so the device wins and its projection is adopted.
* A countdown of zero clears the schedule, which is how expiry takes care of itself.

The stored time is restored across restarts, and validated against the countdown
like any other, so a stale one cannot survive.

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
from homeassistant.helpers.restore_state import RestoreEntity
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

# Writing zero cancels, so a schedule needs at least a minute. The ceiling comes
# from the allowlist rather than being repeated here.
MIN_DELAY_MINUTES = 1

# How far the countdown may sit from the remembered time before the device is taken
# to disagree. Two effects stack: the delay written is the requested time rounded to
# the nearest minute (±30 s), and the countdown only decrements once a minute, so a
# projection from it lags by up to another 60 s. That is 90 s of expected slack, and
# 120 s leaves margin for poll timing. A schedule genuinely changed elsewhere will
# differ by minutes, so this is comfortably inside the gap between drift and change.
COUNTDOWN_TOLERANCE = timedelta(seconds=120)


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


class SydpowerScheduledCharge(SydpowerEntity, DateTimeEntity, RestoreEntity):
    """When charging is scheduled to start, or None when nothing is scheduled."""

    _attr_name = "Scheduled charge"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SydpowerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "scheduled_charge")
        self._target: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Recover the remembered time so a restart does not shift the value."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in (None, "", "unknown", "unavailable"):
            return
        restored = dt_util.parse_datetime(last.state)
        if restored is None:
            _LOGGER.debug("Ignoring unparseable restored value %r", last.state)
            return
        # Not trusted yet: the next read checks it against the countdown and
        # discards it if the device has moved on.
        self._target = dt_util.as_utc(restored)
        _LOGGER.debug("Restored scheduled charge %s, pending verification", self._target)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._input(INPUT_SCHEDULED_CHARGE_COUNTDOWN) is not None
        )

    @property
    def native_value(self) -> datetime | None:
        countdown = self._input(INPUT_SCHEDULED_CHARGE_COUNTDOWN)
        if countdown is None or countdown <= 0:
            # Nothing scheduled: expiry and cancellation both land here.
            self._target = None
            return None

        projected = dt_util.utcnow() + timedelta(minutes=countdown)

        if self._target is not None:
            if abs(projected - self._target) <= COUNTDOWN_TOLERANCE:
                # Countdown agrees: report the time actually asked for, unchanged.
                return self._target
            _LOGGER.debug(
                "Countdown projects %s but %s was remembered; adopting the device's "
                "schedule, which was presumably changed elsewhere",
                projected,
                self._target,
            )

        # No remembered time, or the device disagrees: take its view. Subsequent
        # polls agree with this within the tolerance, so it settles immediately.
        self._target = projected.replace(second=0, microsecond=0)
        return self._target

    async def async_set_value(self, value: datetime) -> None:
        """Schedule charging for *value*, rejecting anything out of range."""
        now = dt_util.utcnow()
        target = dt_util.as_utc(value)
        maximum = _max_delay_minutes()

        # Round rather than truncate: a target 90 seconds away is better honoured as
        # two minutes than as one.
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

        _LOGGER.debug("Scheduling charge for %s, a delay of %d minute(s)", target, delay)
        await self.coordinator.async_write_register(REG_SCHEDULED_CHARGE, delay)
        # Remember what was asked for, not what the delay rounds back to.
        self._target = target
