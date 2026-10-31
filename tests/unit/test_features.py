"""Unit tests for counter calculations, rolling statistics, and feature pipeline."""

from datetime import datetime, timezone

from netcoop.features.counters import WRAP_32_BIT, calculate_counter_rate
from netcoop.features.derived import (
    calculate_drop_ratio,
    calculate_error_ratio,
    calculate_ewma,
    calculate_mad,
    calculate_median,
    calculate_robust_z_score,
    calculate_sma,
    calculate_utilization,
)
from netcoop.features.pipeline import FeaturePipeline
from netcoop.models.observations import MetricObservation


def test_monotonic_counter_rate():
    res = calculate_counter_rate(current_val=15000, previous_val=10000, delta_seconds=10.0)
    assert res.rate == 500.0
    assert res.delta_counter == 5000
    assert res.is_counter_reset is False
    assert res.is_counter_wrap is False


def test_counter_wrap_32_bit():
    # Previous counter was near 2^32, current counter wrapped to 500
    prev = WRAP_32_BIT - 200
    curr = 300
    # Expected delta: (2^32 - prev) + curr = 200 + 300 = 500
    res = calculate_counter_rate(current_val=curr, previous_val=prev, delta_seconds=5.0)
    assert res.is_counter_wrap is True
    assert res.delta_counter == 500
    assert res.rate == 100.0


def test_counter_reset_reboot():
    # Counter dropped from 50000 to 200 (not near wrap threshold)
    res = calculate_counter_rate(current_val=200, previous_val=50000, delta_seconds=10.0)
    assert res.is_counter_reset is True
    assert res.is_counter_wrap is False
    assert res.rate == 20.0  # Uses current_val / delta_seconds baseline
    assert "Counter reset/reboot detected" in res.warning


def test_counter_invalid_delta():
    res = calculate_counter_rate(current_val=100, previous_val=50, delta_seconds=0.0)
    assert res.rate is None
    assert "Invalid delta_seconds" in res.warning


def test_utilization_derivation_and_missing_bandwidth():
    # Known bandwidth: 1000 Mbps, throughput: 850 Mbps -> 85.0%
    util, warn = calculate_utilization(throughput_mbps=850.0, bandwidth_mbps=1000.0)
    assert util == 85.0
    assert warn is None

    # Missing bandwidth: MUST NOT derive utilization or fabricate values
    util_none, warn_none = calculate_utilization(throughput_mbps=850.0, bandwidth_mbps=None)
    assert util_none is None
    assert "missing or non-positive" in warn_none

    # Zero bandwidth
    util_zero, warn_zero = calculate_utilization(throughput_mbps=850.0, bandwidth_mbps=0.0)
    assert util_zero is None
    assert "missing or non-positive" in warn_zero


def test_drop_and_error_ratios():
    # 50 drops out of 950 packets -> 50 / 1000 = 0.05
    ratio, warn = calculate_drop_ratio(queue_drops=50, total_packets=950)
    assert ratio == 0.05
    assert warn is None

    # Error ratio
    err_ratio, err_warn = calculate_error_ratio(interface_errors=10, total_packets=990)
    assert err_ratio == 0.01
    assert err_warn is None

    # Missing packet count
    r_none, w_none = calculate_drop_ratio(queue_drops=50, total_packets=None)
    assert r_none is None
    assert "missing or negative" in w_none


def test_rolling_statistics_sma_and_ewma():
    series = [10.0, 20.0, 30.0, 40.0, 50.0]
    sma = calculate_sma(series, window_size=3)
    # sma: [10, (10+20)/2=15, (10+20+30)/3=20, (20+30+40)/3=30, (30+40+50)/3=40]
    assert sma == [10.0, 15.0, 20.0, 30.0, 40.0]

    ewma = calculate_ewma(series, alpha=0.5)
    assert len(ewma) == 5
    assert ewma[0] == 10.0
    assert ewma[1] == 0.5 * 20.0 + 0.5 * 10.0 == 15.0


def test_mad_and_robust_z_scores():
    # Series with clear outlier: [10, 10, 11, 10, 12, 100]
    series = [10.0, 10.0, 11.0, 10.0, 12.0, 100.0]
    med = calculate_median(series)
    mad = calculate_mad(series)
    assert med == 10.5
    # Absolute deviations: [0.5, 0.5, 0.5, 0.5, 1.5, 89.5] -> median is 0.5
    assert mad == 0.5

    # Outlier 100 has huge robust Z-score
    z_outlier = calculate_robust_z_score(100.0, med, mad)
    assert z_outlier > 100.0

    # Normal point 11 has small robust Z-score
    z_normal = calculate_robust_z_score(11.0, med, mad)
    assert abs(z_normal) < 1.0


def test_feature_pipeline_extraction():
    pipeline = FeaturePipeline()
    t1 = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 31, 12, 1, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 31, 12, 2, 0, tzinfo=timezone.utc)

    observations = [
        MetricObservation(
            observation_id="OBS-1",
            incident_id="INC-1",
            source="test",
            entity_id="SW_CORE_01",
            metric_name="cpu_utilization_pct",
            value=45.0,
            unit="percent",
            timestamp=t1,
        ),
        MetricObservation(
            observation_id="OBS-2",
            incident_id="INC-1",
            source="test",
            entity_id="SW_CORE_01",
            metric_name="cpu_utilization_pct",
            value=50.0,
            unit="percent",
            timestamp=t2,
        ),
        MetricObservation(
            observation_id="OBS-3",
            incident_id="INC-1",
            source="test",
            entity_id="SW_CORE_01",
            metric_name="cpu_utilization_pct",
            value=95.0,
            unit="percent",
            timestamp=t3,
        ),
        # Throughput & bandwidth for utilization derivation
        MetricObservation(
            observation_id="OBS-4",
            incident_id="INC-1",
            source="test",
            entity_id="SW_CORE_01",
            metric_name="throughput_mbps",
            value=920.0,
            unit="mbps",
            timestamp=t3,
        ),
        MetricObservation(
            observation_id="OBS-5",
            incident_id="INC-1",
            source="test",
            entity_id="SW_CORE_01",
            metric_name="bandwidth_mbps",
            value=1000.0,
            unit="mbps",
            timestamp=t3,
        ),
    ]

    features = pipeline.extract_features(observations, incident_id="INC-1")
    assert len(features) > 0

    feature_names = {f.feature_name for f in features}
    assert "cpu_utilization_pct_mean" in feature_names
    assert "cpu_utilization_pct_robust_z" in feature_names
    assert "derived_link_utilization_pct" in feature_names

    # Check provenance
    util_feat = next(f for f in features if f.feature_name == "derived_link_utilization_pct")
    assert util_feat.value == 92.0
    assert "OBS-4" in util_feat.source_observation_ids
    assert "OBS-5" in util_feat.source_observation_ids
