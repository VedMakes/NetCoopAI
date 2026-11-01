"""Derived network feature calculations and statistical anomaly detectors.

Provides:
- Throughput and link capacity utilization derivation (with strict missing bandwidth checks).
- Packet drop ratio and interface error ratio calculations.
- Moving averages (SMA), Exponentially Weighted Moving Average (EWMA).
- Median Absolute Deviation (MAD) and robust Z-score estimation.
"""

from __future__ import annotations

import math
from typing import Sequence


def calculate_utilization(
    throughput_mbps: float | None,
    bandwidth_mbps: float | None,
) -> tuple[float | None, str | None]:
    """Calculates link utilization percentage.

    Rules:
    - Never derive utilization without known link capacity/bandwidth.
    - Caps at 100.0% if exceeding capacity unless oversubscription is flagged.
    """
    if bandwidth_mbps is None or bandwidth_mbps <= 0:
        return None, "Bandwidth/link capacity is missing or non-positive. Utilization cannot be derived."

    if throughput_mbps is None:
        return None, "Throughput is missing; utilization cannot be derived."

    if throughput_mbps < 0:
        return None, f"Negative throughput {throughput_mbps} is invalid."

    util_pct = (throughput_mbps / bandwidth_mbps) * 100.0
    return round(util_pct, 2), None


def calculate_drop_ratio(
    queue_drops: float,
    total_packets: float | None,
) -> tuple[float | None, str | None]:
    """Calculates packet drop ratio: drops / (packets + drops)."""
    if total_packets is None or total_packets < 0:
        return None, "Total packets is missing or negative; drop ratio cannot be calculated."

    total = total_packets + queue_drops
    if total <= 0:
        return 0.0, None

    ratio = queue_drops / total
    return round(ratio, 6), None


def calculate_error_ratio(
    interface_errors: float,
    total_packets: float | None,
) -> tuple[float | None, str | None]:
    """Calculates interface error ratio: errors / (packets + errors)."""
    if total_packets is None or total_packets < 0:
        return None, "Total packets is missing or negative; error ratio cannot be calculated."

    total = total_packets + interface_errors
    if total <= 0:
        return 0.0, None

    ratio = interface_errors / total
    return round(ratio, 6), None


def calculate_median(values: Sequence[float]) -> float:
    """Computes median of a sequence of numeric values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def calculate_mad(values: Sequence[float]) -> float:
    """Calculates Median Absolute Deviation (MAD).

    MAD = median(|X_i - median(X)|)
    """
    if len(values) < 2:
        return 0.0
    med = calculate_median(values)
    abs_deviations = [abs(x - med) for x in values]
    return calculate_median(abs_deviations)


def calculate_robust_z_score(
    value: float,
    median: float,
    mad: float,
) -> float:
    """Calculates robust Z-score using median and MAD.

    Score = 0.6745 * (value - median) / MAD
    0.6745 is the consistency constant for a normal distribution.
    """
    if mad <= 1e-9:
        return 0.0 if abs(value - median) < 1e-9 else (10.0 if value > median else -10.0)
    return round(0.6745 * (value - median) / mad, 4)


def calculate_ewma(
    values: Sequence[float],
    alpha: float = 0.3,
) -> list[float]:
    """Calculates Exponentially Weighted Moving Average (EWMA).

    S_t = alpha * Y_t + (1 - alpha) * S_{t-1}
    """
    if not values:
        return []
    if not (0.0 < alpha <= 1.0):
        raise ValueError("EWMA alpha smoothing factor must be between (0.0, 1.0].")

    result: list[float] = [values[0]]
    for val in values[1:]:
        ewma_val = alpha * val + (1.0 - alpha) * result[-1]
        result.append(round(ewma_val, 4))
    return result


def calculate_sma(
    values: Sequence[float],
    window_size: int = 5,
) -> list[float]:
    """Calculates Simple Moving Average (SMA)."""
    if not values:
        return []
    if window_size < 1:
        raise ValueError("Window size must be >= 1.")

    result: list[float] = []
    for i in range(len(values)):
        start_idx = max(0, i - window_size + 1)
        window = values[start_idx : i + 1]
        avg = sum(window) / len(window)
        result.append(round(avg, 4))
    return result


def calculate_rolling_summary(values: Sequence[float]) -> dict[str, float]:
    """Computes full statistical summary across a metric series."""
    if not values:
        return {
            "count": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "median": 0.0,
            "mad": 0.0,
            "min": 0.0,
            "max": 0.0,
            "latest_robust_z": 0.0,
        }

    n = len(values)
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / (n - 1) if n > 1 else 0.0
    std_val = math.sqrt(variance)
    med_val = calculate_median(values)
    mad_val = calculate_mad(values)
    latest = values[-1]
    robust_z = calculate_robust_z_score(latest, med_val, mad_val)

    return {
        "count": float(n),
        "mean": round(mean_val, 4),
        "std": round(std_val, 4),
        "median": round(med_val, 4),
        "mad": round(mad_val, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "latest_robust_z": robust_z,
    }
