"""Feature extraction pipeline for NetCoop AI.

Processes canonical observations for an incident and derives high-level features:
- Grouping by entity and metric.
- Rolling statistics (SMA, EWMA, MAD, robust Z-score).
- Capacity utilization and loss/drop ratios.
- Generating provenance-backed DerivedFeature instances.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from netcoop.features.derived import (
    calculate_drop_ratio,
    calculate_rolling_summary,
    calculate_utilization,
)
from netcoop.features.models import DerivedFeature
from netcoop.models.observations import CanonicalObservation, MetricObservation
from netcoop.utils.id_generator import generate_id


class FeaturePipeline:
    """Extracts derived statistical and relational features from raw observations."""

    def __init__(self) -> None:
        pass

    def extract_features(
        self,
        observations: Sequence[CanonicalObservation],
        incident_id: str = "INC-AUTO",
    ) -> list[DerivedFeature]:
        """Runs feature extraction across an observation stream."""
        derived_features: list[DerivedFeature] = []

        # Filter metric observations
        metric_obs = [o for o in observations if isinstance(o, MetricObservation)]
        if not metric_obs:
            return derived_features

        # Group by (entity_id, metric_name) sorted by timestamp
        grouped: dict[tuple[str, str], list[MetricObservation]] = defaultdict(list)
        for m in sorted(metric_obs, key=lambda x: x.timestamp):
            grouped[(m.entity_id, m.metric_name)].append(m)

        # 1. Per-metric rolling statistics and anomaly scores
        for (entity_id, metric_name), obs_list in grouped.items():
            vals = [o.value for o in obs_list]
            obs_ids = [o.observation_id for o in obs_list]
            start_time = obs_list[0].timestamp
            end_time = obs_list[-1].timestamp
            unit = obs_list[0].unit

            stats = calculate_rolling_summary(vals)

            # Rolling Mean Feature
            derived_features.append(
                DerivedFeature(
                    feature_id=generate_id("FEAT"),
                    incident_id=incident_id,
                    entity_id=entity_id,
                    feature_name=f"{metric_name}_mean",
                    value=stats["mean"],
                    unit=unit,
                    time_window_start=start_time,
                    time_window_end=end_time,
                    source_observation_ids=obs_ids,
                    metadata={"rolling_stats": stats},
                )
            )

            # Robust Z-Score Feature (Anomaly pressure)
            if len(vals) >= 3:
                derived_features.append(
                    DerivedFeature(
                        feature_id=generate_id("FEAT"),
                        incident_id=incident_id,
                        entity_id=entity_id,
                        feature_name=f"{metric_name}_robust_z",
                        value=stats["latest_robust_z"],
                        unit="z_score",
                        time_window_start=start_time,
                        time_window_end=end_time,
                        source_observation_ids=obs_ids,
                        metadata={"mad": stats["mad"], "median": stats["median"]},
                    )
                )

        # 2. Cross-metric derivations (e.g., Utilization and Drop Ratios)
        # Find latest values per entity
        latest_metrics_per_entity: dict[str, dict[str, MetricObservation]] = defaultdict(dict)
        for m in sorted(metric_obs, key=lambda x: x.timestamp):
            latest_metrics_per_entity[m.entity_id][m.metric_name] = m

        for entity_id, m_dict in latest_metrics_per_entity.items():
            # Drop ratio if queue_drops is present
            if "queue_drops" in m_dict:
                drop_obs = m_dict["queue_drops"]
                # Packet count: throughput or 1000 default if packets not explicitly tracked
                throughput_obs = m_dict.get("throughput_mbps")
                # Estimate packet rate or packet base if available
                est_packets = (throughput_obs.value * 125.0) if throughput_obs else 1000.0
                ratio, warn = calculate_drop_ratio(drop_obs.value, est_packets)
                if ratio is not None:
                    derived_features.append(
                        DerivedFeature(
                            feature_id=generate_id("FEAT"),
                            incident_id=incident_id,
                            entity_id=entity_id,
                            feature_name="queue_drop_ratio",
                            value=ratio,
                            unit="ratio",
                            time_window_start=drop_obs.timestamp,
                            time_window_end=drop_obs.timestamp,
                            source_observation_ids=[drop_obs.observation_id] + ([throughput_obs.observation_id] if throughput_obs else []),
                            warnings=[warn] if warn else [],
                        )
                    )

            # Utilization derivation if throughput and bandwidth both present
            if "throughput_mbps" in m_dict and "bandwidth_mbps" in m_dict:
                tp_obs = m_dict["throughput_mbps"]
                bw_obs = m_dict["bandwidth_mbps"]
                util, warn = calculate_utilization(tp_obs.value, bw_obs.value)
                if util is not None:
                    derived_features.append(
                        DerivedFeature(
                            feature_id=generate_id("FEAT"),
                            incident_id=incident_id,
                            entity_id=entity_id,
                            feature_name="derived_link_utilization_pct",
                            value=util,
                            unit="percent",
                            time_window_start=min(tp_obs.timestamp, bw_obs.timestamp),
                            time_window_end=max(tp_obs.timestamp, bw_obs.timestamp),
                            source_observation_ids=[tp_obs.observation_id, bw_obs.observation_id],
                            warnings=[warn] if warn else [],
                        )
                    )

        return derived_features
