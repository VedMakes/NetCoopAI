"""Unit tests for telemetry normalization, unit conversion, and alias resolution."""

from datetime import timezone

from netcoop.ingestion.aliases import EntityAliasResolver
from netcoop.ingestion.normalization import (
    normalize_metric_name,
    normalize_metric_value_and_unit,
    normalize_timestamp,
)


def test_timestamp_normalization_iso_and_utc():
    # UTC ISO string with Z
    dt, warn = normalize_timestamp("2026-10-31T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.year == 2026
    assert dt.hour == 12
    assert warn is None

    # UTC with explicit offset
    dt2, warn2 = normalize_timestamp("2026-10-31T17:30:00+05:30")
    assert dt2 is not None
    assert dt2.tzinfo == timezone.utc
    assert dt2.hour == 12
    assert dt2.minute == 0
    assert warn2 is None


def test_timestamp_normalization_naive_flags_warning():
    # Naive string gets interpreted under UTC default with a warning
    dt, warn = normalize_timestamp("2026-10-31 12:00:00")
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert warn is not None
    assert "Naive" in warn


def test_timestamp_normalization_epoch():
    # Epoch seconds
    dt, _ = normalize_timestamp(1700000000)
    assert dt is not None
    assert dt.tzinfo == timezone.utc

    # Epoch milliseconds
    dt_ms, _ = normalize_timestamp(1700000000000)
    assert dt_ms is not None
    assert dt_ms == dt


def test_timestamp_normalization_missing_and_invalid():
    dt, warn = normalize_timestamp(None)
    assert dt is None
    assert "Missing" in warn

    dt_inv, warn_inv = normalize_timestamp("invalid-date-string-12345")
    assert dt_inv is None
    assert "Unsupported" in warn_inv


def test_unit_conversion_percent():
    # Fraction to percent
    val, unit, warns = normalize_metric_value_and_unit("cpu_utilization_pct", 0.75, "fraction")
    assert val == 75.0
    assert unit == "percent"
    assert len(warns) == 0

    # Direct percent symbol
    val2, unit2, warns2 = normalize_metric_value_and_unit("cpu_utilization_pct", 88.5, "%")
    assert val2 == 88.5
    assert unit2 == "percent"


def test_unit_conversion_latency_and_bandwidth():
    # Seconds to milliseconds
    val_ms, unit_ms, warns_ms = normalize_metric_value_and_unit("latency_ms", 0.25, "seconds")
    assert val_ms == 250.0
    assert unit_ms == "milliseconds"

    # Microseconds to milliseconds
    val_us, unit_us, _ = normalize_metric_value_and_unit("latency_ms", 1500, "microseconds")
    assert val_us == 1.5
    assert unit_us == "milliseconds"

    # kbps to mbps
    val_mb, unit_mb, _ = normalize_metric_value_and_unit("throughput_mbps", 50000, "kbps")
    assert val_mb == 50.0
    assert unit_mb == "mbps"

    # gbps to mbps
    val_gb, unit_gb, _ = normalize_metric_value_and_unit("bandwidth_mbps", 10, "gbps")
    assert val_gb == 10000.0
    assert unit_gb == "mbps"


def test_unit_conversion_never_coerces_missing_to_zero():
    # Missing / None value
    val, unit, warns = normalize_metric_value_and_unit("cpu_utilization_pct", None, "percent")
    assert val is None
    assert any("will not be coerced to zero" in w for w in warns)

    # Empty string
    val_empty, _, warns_empty = normalize_metric_value_and_unit("queue_drops", "", "count")
    assert val_empty is None
    assert any("will not be coerced to zero" in w for w in warns_empty)


def test_out_of_bounds_detection():
    # CPU utilization cannot exceed 100%
    val, unit, warns = normalize_metric_value_and_unit("cpu_utilization_pct", 125.0, "percent")
    assert val == 125.0
    assert any("exceeds maximum" in w for w in warns)

    # Negative queue drops
    val_neg, _, warns_neg = normalize_metric_value_and_unit("queue_drops", -5, "count")
    assert any("below minimum" in w for w in warns_neg)


def test_metric_name_synonyms():
    canon, warn = normalize_metric_name("cpu")
    assert canon == "cpu_utilization_pct"
    assert warn is None

    canon2, _ = normalize_metric_name("rtt")
    assert canon2 == "latency_ms"

    canon3, _ = normalize_metric_name("drops")
    assert canon3 == "queue_drops"

    # Unknown metric
    canon_unk, warn_unk = normalize_metric_name("totally_fake_custom_metric_xyz")
    assert canon_unk is None
    assert "not found in vocabulary" in warn_unk


def test_entity_alias_resolution():
    resolver = EntityAliasResolver()

    # Known standard alias
    res1 = resolver.resolve("SW_CAMPUS_1")
    assert res1.canonical_id == "SW_CORE_01"
    assert res1.is_known is True
    assert res1.is_ambiguous is False

    res2 = resolver.resolve("SW_CORE")
    assert res2.canonical_id == "SW_CORE_01"

    # Canonical name passthrough
    res3 = resolver.resolve("SW_CORE_01")
    assert res3.canonical_id == "SW_CORE_01"

    # Empty name
    res4 = resolver.resolve("")
    assert res4.canonical_id == "UNKNOWN"
    assert res4.is_known is False


def test_entity_alias_ambiguity_rejection():
    resolver = EntityAliasResolver()
    # Register conflict: ALIAS_X maps to DEV_A, then to DEV_B
    resolver.register_alias("ALIAS_CONFLICT", "DEV_A")
    resolver.register_alias("ALIAS_CONFLICT", "DEV_B")

    res = resolver.resolve("ALIAS_CONFLICT")
    assert res.is_ambiguous is True
    assert "ambiguous" in res.warning
