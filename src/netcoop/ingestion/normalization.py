"""Telemetry normalization and data-quality enforcement.

Normalizes timestamps to timezone-aware UTC, converts units to canonical representations,
maps metric names to canonical vocabulary, and strictly rejects silent coercion of missing values.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from netcoop.communication.vocabulary import get_metric_definition
from netcoop.models.observations import MetricObservation


@dataclass
class NormalizationWarning:
    record_id: str
    warning_type: str  # missing_value, unknown_unit, out_of_bounds, ambiguous_timestamp, alias_unresolved
    message: str
    raw_value: Any = None


@dataclass
class NormalizedMetricResult:
    observation: MetricObservation | None
    warnings: list[NormalizationWarning] = field(default_factory=list)
    quarantined: bool = False
    quarantine_reason: str | None = None


# Metric name synonym mapping to canonical vocabulary
METRIC_SYNONYMS: dict[str, str] = {
    # CPU
    "cpu": "cpu_utilization_pct",
    "cpu_pct": "cpu_utilization_pct",
    "cpu_usage": "cpu_utilization_pct",
    "cpu_util": "cpu_utilization_pct",
    "cpu_utilization": "cpu_utilization_pct",
    "cpu_utilization_pct": "cpu_utilization_pct",
    # Memory
    "mem": "memory_utilization_pct",
    "memory": "memory_utilization_pct",
    "mem_pct": "memory_utilization_pct",
    "memory_pct": "memory_utilization_pct",
    "memory_utilization": "memory_utilization_pct",
    "memory_utilization_pct": "memory_utilization_pct",
    # Link utilization
    "utilization": "link_utilization_pct",
    "link_util": "link_utilization_pct",
    "link_util_pct": "link_utilization_pct",
    "link_utilization": "link_utilization_pct",
    "link_utilization_pct": "link_utilization_pct",
    # Packet loss
    "loss": "packet_loss_pct",
    "packet_loss": "packet_loss_pct",
    "loss_pct": "packet_loss_pct",
    "packet_loss_pct": "packet_loss_pct",
    # Latency
    "rtt": "latency_ms",
    "latency": "latency_ms",
    "delay": "latency_ms",
    "latency_ms": "latency_ms",
    # Jitter
    "jitter": "jitter_ms",
    "jitter_ms": "jitter_ms",
    # Queue drops
    "drops": "queue_drops",
    "drop_count": "queue_drops",
    "egress_drops": "queue_drops",
    "queue_drops": "queue_drops",
    # Interface errors
    "errors": "interface_errors",
    "interface_errs": "interface_errors",
    "crc_errors": "interface_errors",
    "input_errors": "interface_errors",
    "interface_errors": "interface_errors",
    # Link flaps
    "flaps": "link_flaps",
    "link_flaps": "link_flaps",
    "state_changes": "link_flaps",
    # Bandwidth & Throughput
    "bandwidth": "bandwidth_mbps",
    "bandwidth_mbps": "bandwidth_mbps",
    "speed": "bandwidth_mbps",
    "throughput": "throughput_mbps",
    "throughput_mbps": "throughput_mbps",
    "traffic_rate": "throughput_mbps",
    # Wireless
    "rssi": "rssi_dbm",
    "rssi_dbm": "rssi_dbm",
    "signal": "rssi_dbm",
    "snr": "snr_db",
    "snr_db": "snr_db",
}


def normalize_timestamp(
    ts_val: Any, default_tz: timezone = timezone.utc
) -> tuple[datetime | None, str | None]:
    """Parses and normalizes a timestamp value to timezone-aware UTC.

    Returns (normalized_datetime, warning_string).
    """
    if ts_val is None or ts_val == "":
        return None, "Missing timestamp value."

    if isinstance(ts_val, datetime):
        if ts_val.tzinfo is None:
            return ts_val.replace(tzinfo=default_tz).astimezone(timezone.utc), "Naive datetime interpreted with default timezone."
        return ts_val.astimezone(timezone.utc), None

    if isinstance(ts_val, (int, float)):
        # Epoch seconds or milliseconds
        if ts_val > 1e11:  # Milliseconds
            return datetime.fromtimestamp(ts_val / 1000.0, tz=timezone.utc), None
        return datetime.fromtimestamp(float(ts_val), tz=timezone.utc), None

    if isinstance(ts_val, str):
        cleaned = ts_val.strip()
        # Handle trailing Z
        if cleaned.endswith("Z") or cleaned.endswith("z"):
            cleaned = cleaned[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=default_tz).astimezone(timezone.utc), "Naive ISO timestamp interpreted with default timezone."
            return dt.astimezone(timezone.utc), None
        except ValueError:
            pass

        # Try common alternative formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(cleaned, fmt)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=default_tz).astimezone(timezone.utc), "Naive datetime string interpreted with default timezone."
                return dt.astimezone(timezone.utc), None
            except ValueError:
                continue

    return None, f"Unsupported timestamp format: {ts_val!r}"


def normalize_metric_value_and_unit(
    canonical_metric: str,
    raw_value: Any,
    raw_unit: str | None,
) -> tuple[float | None, str | None, list[str]]:
    """Normalizes a raw metric value and unit to canonical representation.

    Rules:
    - Never convert None/missing to 0.0.
    - Convert units if known conversion exists (e.g. seconds -> milliseconds, kbps -> mbps, fraction -> percent).
    - Returns (canonical_value, canonical_unit, list_of_warnings).
    """
    warnings: list[str] = []

    if raw_value is None or raw_value == "":
        return None, None, ["Metric value is missing (will not be coerced to zero)."]

    try:
        val = float(raw_value)
    except (ValueError, TypeError):
        return None, None, [f"Metric value '{raw_value}' cannot be converted to float."]

    defn = get_metric_definition(canonical_metric)
    if not defn:
        return None, None, [f"Metric '{canonical_metric}' is not in canonical vocabulary."]

    target_unit = defn.get("unit")
    norm_unit = raw_unit.strip().lower() if raw_unit else target_unit

    # Unit conversion logic
    if target_unit == "percent":
        if norm_unit in ("%", "pct", "percent", "percentage"):
            # Already percent
            pass
        elif norm_unit in ("fraction", "ratio", "decimal"):
            if 0.0 <= val <= 1.0:
                val = val * 100.0
                norm_unit = "percent"
            else:
                warnings.append(f"Ratio value {val} out of expected [0, 1] range before percent conversion.")
        elif norm_unit == target_unit:
            pass
        else:
            warnings.append(f"Unrecognized unit '{norm_unit}' for percent metric '{canonical_metric}'.")
            return None, None, warnings

    elif target_unit == "milliseconds":
        if norm_unit in ("ms", "milliseconds", "msec"):
            norm_unit = "milliseconds"
        elif norm_unit in ("s", "sec", "seconds"):
            val = val * 1000.0
            norm_unit = "milliseconds"
        elif norm_unit in ("us", "usec", "microseconds"):
            val = val / 1000.0
            norm_unit = "milliseconds"
        elif norm_unit == target_unit:
            pass
        else:
            warnings.append(f"Unrecognized unit '{norm_unit}' for millisecond metric '{canonical_metric}'.")
            return None, None, warnings

    elif target_unit == "mbps":
        if norm_unit in ("mbps", "mb/s", "megabits/sec"):
            norm_unit = "mbps"
        elif norm_unit in ("kbps", "kb/s", "kilobits/sec"):
            val = val / 1000.0
            norm_unit = "mbps"
        elif norm_unit in ("gbps", "gb/s", "gigabits/sec"):
            val = val * 1000.0
            norm_unit = "mbps"
        elif norm_unit in ("bps", "bits/sec"):
            val = val / 1_000_000.0
            norm_unit = "mbps"
        elif norm_unit in ("bytes/sec", "b/s"):
            val = (val * 8.0) / 1_000_000.0
            norm_unit = "mbps"
        elif norm_unit == target_unit:
            pass
        else:
            warnings.append(f"Unrecognized unit '{norm_unit}' for bandwidth metric '{canonical_metric}'.")
            return None, None, warnings

    elif target_unit == "count":
        if norm_unit in ("count", "packets", "drops", "errors", "flaps", "pkts", "frames"):
            norm_unit = "count"
        elif norm_unit == target_unit:
            pass
        else:
            warnings.append(f"Unrecognized unit '{norm_unit}' for count metric '{canonical_metric}'.")
            return None, None, warnings

    elif target_unit in ("dbm", "db"):
        accepted_units = {target_unit, "db", "dbm", "decibel", "decibels"}
        if norm_unit not in accepted_units:
            warnings.append(f"Unrecognized unit '{norm_unit}' for signal metric '{canonical_metric}'.")
            return None, None, warnings
        norm_unit = target_unit

    # Bounds checking
    min_val = defn.get("min")
    max_val = defn.get("max")
    if min_val is not None and val < float(min_val):
        warnings.append(f"Metric '{canonical_metric}' value {val} is below minimum {min_val}.")
    if max_val is not None and val > float(max_val):
        warnings.append(f"Metric '{canonical_metric}' value {val} exceeds maximum {max_val}.")

    return round(val, 4), target_unit, warnings


def normalize_metric_name(
    raw_name: str, profile_aliases: dict[str, str] | None = None
) -> tuple[str | None, str | None]:
    """Maps a raw metric name to its canonical vocabulary counterpart.

    Returns (canonical_name, warning).
    """
    if not raw_name or not raw_name.strip():
        return None, "Empty metric name."

    clean = raw_name.strip().lower()
    if profile_aliases:
        aliases = {key.strip().casefold(): value for key, value in profile_aliases.items()}
        if clean in aliases:
            return aliases[clean], None
    if clean in METRIC_SYNONYMS:
        return METRIC_SYNONYMS[clean], None

    # Check if directly in vocabulary
    if get_metric_definition(clean):
        return clean, None

    return None, f"Unknown metric name '{raw_name}' not found in vocabulary."
