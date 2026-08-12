"""
Compensation for the device's own power-reporting error, fitted from measurements.

The device under-reports its AC output while it is simultaneously charging. This
was established against two independent external instruments — a plug meter on the
wall socket and a UPS reporting its own real power — by stopping charging
mid-measurement with nothing else altered:

    SOC     input[6]  input[39]  input[3]   true load
  95.7%          608        358       249      ~490 W
  95.7%          497        497         0      ~490 W   charging stopped

Register 39 jumped ~130 W against an unchanged load. Register 3 (charge power) is
accurate, and register 6 is low by the same amount as 39 because the device derives
it as ``39 + 3`` rather than measuring it.

**The shape of the error cannot be settled from one charge rate.** A flat ~130 W and
~0.53 x the charge power fit that measurement equally well, and they diverge sharply
elsewhere. Rather than pick one, this module fits ``error = offset + slope x charge``
to however many observations are supplied:

* One observation, or several at the same charge rate, can only support an offset.
  The slope stays zero and is reported as unresolved.
* Two or more at *different* charge rates separate the two terms by least squares,
  which is what distinguishes a fixed shortfall from a proportional one.

Each observation carries what an external meter and the device say at one moment.
The wall meter and the load's own reporting give the true figures; their difference
gives the true charge power, which is worth capturing because it independently
checks register 3 rather than trusting it.

A caveat no amount of fitting escapes: if the unit serves part of the load through a
bypass relay and part through the inverter, register 39 counts only the inverter's
share, so the error tracks the load split and no function of charge power describes
it. Residuals across observations at differing loads are what would reveal that,
which is why ``fit_correction`` reports the worst one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class CalibrationSample:
    """
    One simultaneous observation of the device and external instruments.

    ``charge_reported`` is register 3 and is the variable the error is fitted
    against. The remaining fields are optional in pairs: supply true and reported
    output to measure the output error, true and reported input for the input
    error, or both. Anything absent is simply not used.

    All values are watts.
    """

    charge_reported: float
    out_reported: float | None = None
    out_true: float | None = None
    in_reported: float | None = None
    in_true: float | None = None

    @property
    def charge_true(self) -> float | None:
        """
        True charge power, as wall draw less the load.

        Available only when both true figures were supplied. This is the figure
        that showed register 3 to be accurate — 249 W reported against 254 W
        derived this way — so it is a check on the device rather than an input to
        the fit.
        """
        if self.in_true is None or self.out_true is None:
            return None
        return self.in_true - self.out_true

    @property
    def charge_error(self) -> float | None:
        """How far register 3 is from the derived truth, or None if unknown."""
        true = self.charge_true
        return None if true is None else true - self.charge_reported

    @property
    def error(self) -> float | None:
        """
        Watts the device under-reports, averaged over whichever pairs were given.

        The output and input errors should agree, register 6 being derived from
        register 39. Averaging rather than preferring one keeps a single noisy
        reading from dominating; a genuine disagreement shows up as a residual.
        """
        errors = [
            true - reported
            for true, reported in (
                (self.out_true, self.out_reported),
                (self.in_true, self.in_reported),
            )
            if true is not None and reported is not None
        ]
        if not errors:
            return None
        return sum(errors) / len(errors)


@dataclass(frozen=True)
class CorrectionModel:
    """
    A fitted correction: ``offset + slope x charge_power`` watts while charging.

    ``samples`` is how many observations contributed and ``slope_resolved`` says
    whether they spanned more than one charge rate. With it false the slope is zero
    by assumption rather than by measurement, so the correction is only as good as
    the charge rate it was measured at. ``worst_residual`` is the largest gap
    between a fitted and an observed error, in watts — small means the model
    describes the device, large means the error depends on something not captured
    here, such as the load split.
    """

    offset: float = 0.0
    slope: float = 0.0
    samples: int = 0
    slope_resolved: bool = False
    worst_residual: float = 0.0

    @property
    def active(self) -> bool:
        """Whether this model would change any reading."""
        return bool(self.samples) and (self.offset != 0.0 or self.slope != 0.0)

    def watts(self, charge_power: float | int | None) -> float:
        """
        Watts to add to a reported output or input figure.

        Zero unless the device is charging, that being the only state in which the
        error has been observed — in pass-through register 39 agreed with the
        external instruments to within 1.5%, so correcting there would introduce an
        error rather than remove one. A missing charge reading counts as not
        charging, so it can never manufacture a correction.
        """
        if not charge_power or charge_power <= 0:
            return 0.0
        return self.offset + self.slope * float(charge_power)


NO_CORRECTION = CorrectionModel()


def fit_correction(samples: list[CalibrationSample]) -> CorrectionModel:
    """
    Least-squares fit of ``error = offset + slope x charge`` over *samples*.

    Observations without a usable error pair are ignored. When every remaining
    observation shares one charge rate — including the single-observation case —
    the slope cannot be separated from the offset, so the mean error becomes the
    offset and the slope is left at zero and flagged unresolved.
    """
    points = [(s.charge_reported, s.error) for s in samples if s.error is not None]
    points = [(x, e) for x, e in points if e is not None]
    if not points:
        return NO_CORRECTION

    n = len(points)
    distinct_x = {x for x, _ in points}

    if len(distinct_x) < 2:
        # One charge rate: offset only. Fitting a slope here would just divide the
        # observed error by an arbitrary x and look precise while being a guess.
        offset = sum(e for _, e in points) / n
        residual = max(abs(e - offset) for _, e in points)
        return CorrectionModel(
            offset=offset,
            slope=0.0,
            samples=n,
            slope_resolved=False,
            worst_residual=residual,
        )

    sum_x = sum(x for x, _ in points)
    sum_e = sum(e for _, e in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xe = sum(x * e for x, e in points)
    denominator = n * sum_xx - sum_x * sum_x

    slope = (n * sum_xe - sum_x * sum_e) / denominator
    offset = (sum_e - slope * sum_x) / n
    residual = max(abs(e - (offset + slope * x)) for x, e in points)
    return CorrectionModel(
        offset=offset,
        slope=slope,
        samples=n,
        slope_resolved=True,
        worst_residual=residual,
    )
