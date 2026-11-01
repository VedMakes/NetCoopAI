"""Network counter processing and rate calculation.

Handles 32-bit/64-bit wraps, reboots/resets, and prevents spurious negative rates
or astronomical spike artifacts.
"""

from dataclasses import dataclass

WRAP_32_BIT = 2**32
WRAP_64_BIT = 2**64


@dataclass(frozen=True)
class CounterRateResult:
    rate: float | None
    delta_counter: float | None
    delta_seconds: float
    is_counter_reset: bool = False
    is_counter_wrap: bool = False
    warning: str | None = None


def calculate_counter_rate(
    current_val: float,
    previous_val: float,
    delta_seconds: float,
    max_wrap_val: int = WRAP_32_BIT,
) -> CounterRateResult:
    """Calculates per-second rate between two cumulative counter samples.

    Rules:
    - If delta_seconds <= 0: invalid interval.
    - If current >= previous: normal monotonic progression.
    - If current < previous:
        - Check if consistent with counter wrap (previous was near max_wrap_val, e.g. within 10% of max).
        - Otherwise, treat as device reboot/counter reset: do not fabricate negative rates.
    """
    if delta_seconds <= 0:
        return CounterRateResult(
            rate=None,
            delta_counter=None,
            delta_seconds=delta_seconds,
            warning=f"Invalid delta_seconds {delta_seconds} <= 0.",
        )

    # Monotonic progression
    if current_val >= previous_val:
        delta = current_val - previous_val
        rate = delta / delta_seconds
        return CounterRateResult(
            rate=round(rate, 4),
            delta_counter=delta,
            delta_seconds=delta_seconds,
        )

    # current_val < previous_val: either wrap or reset
    # Check if wrap: previous was close to wrap limit
    threshold_32 = 0.9 * WRAP_32_BIT
    threshold_64 = 0.9 * WRAP_64_BIT

    if previous_val >= threshold_32 and previous_val < WRAP_32_BIT:
        # 32-bit wrap
        wrapped_delta = (WRAP_32_BIT - previous_val) + current_val
        rate = wrapped_delta / delta_seconds
        return CounterRateResult(
            rate=round(rate, 4),
            delta_counter=wrapped_delta,
            delta_seconds=delta_seconds,
            is_counter_wrap=True,
            warning="32-bit counter wrap detected and normalized.",
        )
    elif previous_val >= threshold_64:
        # 64-bit wrap
        wrapped_delta = (WRAP_64_BIT - previous_val) + current_val
        rate = wrapped_delta / delta_seconds
        return CounterRateResult(
            rate=round(rate, 4),
            delta_counter=wrapped_delta,
            delta_seconds=delta_seconds,
            is_counter_wrap=True,
            warning="64-bit counter wrap detected and normalized.",
        )
    else:
        # Counter reset / reboot
        # Do not calculate negative rate or bogus huge spike; use current_val as new baseline
        return CounterRateResult(
            rate=round(current_val / delta_seconds, 4),
            delta_counter=current_val,
            delta_seconds=delta_seconds,
            is_counter_reset=True,
            warning=f"Counter reset/reboot detected (decreased from {previous_val} to {current_val}). Rate calculated from zero baseline.",
        )
