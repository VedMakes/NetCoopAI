"""Data ingestion loaders for JSON, CSV, and JSONL network telemetry.

Supports:
1. NetCoop canonical observation manifests (JSON).
2. Organizer-provided single and multi-step JSON telemetry (sample_generator format).
3. Wide and narrow CSV metric files.
4. JSONL log streams.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from netcoop.configuration.profile import NetworkProfile
from netcoop.ingestion.aliases import EntityAliasResolver
from netcoop.ingestion.normalization import (
    NormalizationWarning,
    normalize_metric_name,
    normalize_metric_value_and_unit,
    normalize_timestamp,
)
from netcoop.models.observations import (
    CanonicalObservation,
    ConfigObservation,
    LogObservation,
    MetricObservation,
    TopologyObservation,
)
from netcoop.utils.id_generator import generate_id


@dataclass
class IngestionBatchResult:
    incident_id: str
    observations: list[CanonicalObservation] = field(default_factory=list)
    warnings: list[NormalizationWarning] = field(default_factory=list)
    quarantined_records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.observations)

    @property
    def metric_count(self) -> int:
        return sum(1 for o in self.observations if isinstance(o, MetricObservation))

    @property
    def log_count(self) -> int:
        return sum(1 for o in self.observations if isinstance(o, LogObservation))

    @property
    def topology_count(self) -> int:
        return sum(1 for o in self.observations if isinstance(o, TopologyObservation))

    @property
    def config_count(self) -> int:
        return sum(1 for o in self.observations if isinstance(o, ConfigObservation))


class TelemetryLoader:
    """Loads and normalizes telemetry data from multiple source formats."""

    def __init__(
        self,
        alias_resolver: EntityAliasResolver | None = None,
        profile: NetworkProfile | None = None,
    ) -> None:
        self.profile = profile
        if alias_resolver is not None:
            self.alias_resolver = alias_resolver
        elif profile is not None:
            self.alias_resolver = EntityAliasResolver(
                profile.aliases(), include_campus_defaults=False
            )
        else:
            self.alias_resolver = EntityAliasResolver()

    def _metric_name(self, source_name: str) -> tuple[str | None, str | None]:
        mapping = self.profile.map_metric(source_name) if self.profile else None
        if mapping:
            return mapping.canonical_name, None
        aliases = (
            {name: spec.canonical_name for name, spec in self.profile.metric_mappings.items()}
            if self.profile else None
        )
        return normalize_metric_name(source_name, aliases)

    def _profile_unit(self, source_name: str, raw_unit: str | None) -> str | None:
        if raw_unit or self.profile is None:
            return raw_unit
        mapping = self.profile.map_metric(source_name)
        return mapping.source_unit if mapping else raw_unit

    def _field_candidates(self, canonical_field: str) -> list[str]:
        if self.profile:
            return self.profile.source_field_candidates(canonical_field)
        return {
            "entity_id": ["device_id", "entity_id", "device", "node"],
            "timestamp": ["timestamp", "event_time", "time", "datetime"],
            "metric": ["metric", "metric_name", "measurement"],
            "value": ["value", "reading"],
            "unit": ["unit", "units"],
            "incident_id": ["incident_id"],
            "source_id": ["source_id", "source"],
            "metrics": ["metrics"],
            "message": ["message", "msg"],
            "log_level": ["log_level", "level", "severity"],
            "facility": ["facility"],
            "source_entity": ["source_entity", "src", "from"],
            "target_entity": ["target_entity", "dst", "to"],
            "relationship_type": ["relationship_type", "link_type", "type"],
            "link_id": ["link_id", "id"],
            "capacity_mbps": ["capacity_mbps", "speed_mbps", "capacity"],
            "interface_name": ["interface_name", "source_interface", "interface"],
            "consumer_entity": ["consumer_entity", "consumer", "client"],
            "provider_entity": ["provider_entity", "provider", "server"],
        }.get(canonical_field, [])

    def _field(self, record: dict[str, Any], canonical_field: str) -> Any:
        for candidate in self._field_candidates(canonical_field):
            if candidate in record and record[candidate] is not None:
                return record[candidate]
        return None

    def load_file(
        self,
        file_path: str | Path,
        incident_id: str | None = None,
        default_source: str = "telemetry/loader",
    ) -> IngestionBatchResult:
        """Automatically detects format and loads the specified file."""
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Telemetry file not found: {p}")

        inc_id = incident_id or f"INC-{p.stem.upper()}"
        suffix = p.suffix.lower()

        if suffix == ".json":
            return self.load_json(p, inc_id, default_source)
        elif suffix == ".csv":
            return self.load_csv(p, inc_id, default_source)
        elif suffix in (".jsonl", ".log"):
            return self.load_jsonl(p, inc_id, default_source)
        else:
            raise ValueError(f"Unsupported file format '{suffix}'. Supported: .json, .csv, .jsonl, .log (JSON Lines)")

    # ---------------- JSON Loader ----------------
    def load_json(
        self,
        file_path: str | Path,
        incident_id: str = "INC-AUTO",
        default_source: str = "telemetry/json",
    ) -> IngestionBatchResult:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self.load_json_data(data, incident_id, default_source)

    def load_json_data(
        self,
        data: Any,
        incident_id: str = "INC-AUTO",
        default_source: str = "telemetry/json",
    ) -> IngestionBatchResult:
        result = IngestionBatchResult(incident_id=incident_id)

        # 1. Canonical NetCoop Multi-Observation Manifest
        if isinstance(data, dict) and "observations" in data and isinstance(data["observations"], list):
            actual_inc_id = data.get("incident_id", incident_id)
            result.incident_id = actual_inc_id
            for idx, raw_obs in enumerate(data["observations"]):
                try:
                    obs_type = raw_obs.get("observation_type")
                    if obs_type == "metric":
                        obs = MetricObservation.model_validate(raw_obs)
                    elif obs_type == "log":
                        obs = LogObservation.model_validate(raw_obs)
                    elif obs_type == "topology":
                        obs = TopologyObservation.model_validate(raw_obs)
                    elif obs_type == "config":
                        obs = ConfigObservation.model_validate(raw_obs)
                    else:
                        raise ValueError(f"Unrecognized observation_type: '{obs_type}'")
                    result.observations.append(obs)
                    schema_version = raw_obs.get("schema_version", "1.0")
                    if schema_version != "1.0":
                        result.warnings.append(NormalizationWarning(
                            record_id=raw_obs.get("observation_id", f"obs-{idx}"),
                            warning_type="schema_version_warning",
                            message=f"Unsupported schema_version {schema_version!r}; parsed best-effort as 1.0.",
                            raw_value=schema_version,
                        ))
                except Exception as exc:
                    result.quarantined_records.append({"index": idx, "raw": raw_obs, "error": str(exc)})
                    result.warnings.append(
                        NormalizationWarning(
                            record_id=raw_obs.get("observation_id", f"obs-{idx}"),
                            warning_type="validation_error",
                            message=str(exc),
                            raw_value=raw_obs,
                        )
                    )
            return result

        # 2. Organizer Single Record (Colab format)
        if isinstance(data, dict) and self._field(data, "entity_id") and isinstance(self._field(data, "metrics"), dict):
            self._parse_organizer_record(data, result, default_source)
            return result

        # 3. List of records (Organizer multi-step or array of records)
        if isinstance(data, list):
            for idx, item in enumerate(data):
                if isinstance(item, dict) and self._field(item, "entity_id") and isinstance(self._field(item, "metrics"), dict):
                    self._parse_organizer_record(item, result, default_source)
                elif isinstance(item, dict) and "observation_type" in item:
                    try:
                        obs_type = item["observation_type"]
                        if obs_type == "metric":
                            result.observations.append(MetricObservation.model_validate(item))
                        elif obs_type == "log":
                            result.observations.append(LogObservation.model_validate(item))
                        elif obs_type == "topology":
                            result.observations.append(TopologyObservation.model_validate(item))
                        elif obs_type == "config":
                            result.observations.append(ConfigObservation.model_validate(item))
                    except Exception as exc:
                        result.quarantined_records.append({"index": idx, "raw": item, "error": str(exc)})
                else:
                    result.quarantined_records.append(
                        {"index": idx, "raw": item, "error": "Unrecognized JSON object structure."}
                    )
            return result

        result.quarantined_records.append({"raw": data, "error": "Unrecognized top-level JSON structure."})
        return result

    def _parse_organizer_record(
        self,
        record: dict[str, Any],
        batch: IngestionBatchResult,
        default_source: str,
    ) -> None:
        schema_version = record.get("schema_version", "1.0")
        if schema_version != "1.0":
            batch.warnings.append(NormalizationWarning(
                record_id=str(record.get("device_id", "unknown")),
                warning_type="schema_version_warning",
                message=f"Unsupported schema_version {schema_version!r}; recognized fields parsed best-effort as 1.0.",
                raw_value=schema_version,
            ))
        raw_dev = self._field(record, "entity_id") or ""
        res = self.alias_resolver.resolve(str(raw_dev))
        entity_id = res.canonical_id
        if res.warning:
            batch.warnings.append(
                NormalizationWarning(
                    record_id=str(raw_dev),
                    warning_type="alias_warning",
                    message=res.warning,
                    raw_value=raw_dev,
                )
            )

        raw_ts = self._field(record, "timestamp")
        ts, ts_warn = normalize_timestamp(raw_ts)
        if ts_warn:
            batch.warnings.append(
                NormalizationWarning(
                    record_id=entity_id,
                    warning_type="timestamp_warning",
                    message=ts_warn,
                    raw_value=raw_ts,
                )
            )
        if ts is None:
            batch.quarantined_records.append(
                {"raw": record, "error": "Missing or unparseable timestamp; record quarantined."}
            )
            return

        raw_metrics = self._field(record, "metrics") or {}
        if not isinstance(raw_metrics, dict):
            batch.quarantined_records.append(
                {"raw": record, "error": "Metrics field must be a key-value dictionary."}
            )
            return

        for raw_metric_name, raw_val in raw_metrics.items():
            if raw_val is None:
                # Never coerce missing to zero!
                batch.warnings.append(
                    NormalizationWarning(
                        record_id=f"{entity_id}:{raw_metric_name}",
                        warning_type="missing_value",
                        message=f"Metric '{raw_metric_name}' on '{entity_id}' is null/missing (will not be coerced to zero).",
                        raw_value=None,
                    )
                )
                continue

            canon_name, name_warn = self._metric_name(raw_metric_name)
            if name_warn:
                batch.warnings.append(
                    NormalizationWarning(
                        record_id=f"{entity_id}:{raw_metric_name}",
                        warning_type="unknown_metric",
                        message=name_warn,
                        raw_value=raw_metric_name,
                    )
                )
                continue

            val, unit, val_warns = normalize_metric_value_and_unit(
                canon_name, raw_val, self._profile_unit(raw_metric_name, None)
            )
            for w in val_warns:
                batch.warnings.append(
                    NormalizationWarning(
                        record_id=f"{entity_id}:{canon_name}",
                        warning_type="value_quality",
                        message=w,
                        raw_value=raw_val,
                    )
                )

            if val is not None and unit is not None:
                obs = MetricObservation(
                    observation_id=generate_id("OBS"),
                    incident_id=batch.incident_id,
                    source=default_source,
                    entity_id=entity_id,
                    metric_name=canon_name,
                    value=val,
                    unit=unit,
                    timestamp=ts,
                    raw_reference={"source_file": "json", "device_id": raw_dev, "raw_metric": raw_metric_name, "raw_value": raw_val},
                )
                batch.observations.append(obs)

    # ---------------- CSV Loader ----------------
    def load_csv(
        self,
        file_path: str | Path,
        incident_id: str = "INC-AUTO",
        default_source: str = "telemetry/csv",
    ) -> IngestionBatchResult:
        result = IngestionBatchResult(incident_id=incident_id)

        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = [fn.strip() for fn in (reader.fieldnames or [])]

            # Detect wide vs narrow CSV
            # Narrow: has 'metric_name' and 'value'
            metric_fields = {name.casefold() for name in self._field_candidates("metric")}
            is_narrow = any(fn.lower() in metric_fields for fn in fieldnames)

            for row_idx, row in enumerate(reader):
                try:
                    if is_narrow:
                        self._parse_narrow_csv_row(row, row_idx, result, default_source)
                    else:
                        self._parse_wide_csv_row(row, row_idx, result, default_source)
                except Exception as exc:
                    result.quarantined_records.append({"row_index": row_idx, "row": row, "error": str(exc)})

        return result

    def _parse_narrow_csv_row(
        self,
        row: dict[str, Any],
        row_idx: int,
        batch: IngestionBatchResult,
        default_source: str,
    ) -> None:
        raw_dev = self._field(row, "entity_id") or ""
        res = self.alias_resolver.resolve(raw_dev)
        entity_id = res.canonical_id
        if res.warning:
            batch.warnings.append(NormalizationWarning(entity_id, "alias_warning", res.warning, raw_dev))

        raw_ts = self._field(row, "timestamp")
        ts, ts_warn = normalize_timestamp(raw_ts)
        if ts_warn:
            batch.warnings.append(NormalizationWarning(entity_id, "timestamp_warning", ts_warn, raw_ts))
        if ts is None:
            batch.quarantined_records.append({"row_index": row_idx, "row": row, "error": "Missing timestamp"})
            return

        raw_metric = self._field(row, "metric") or ""
        canon_metric, name_warn = self._metric_name(raw_metric)
        if name_warn:
            batch.warnings.append(NormalizationWarning(entity_id, "unknown_metric", name_warn, raw_metric))
            return

        raw_val = self._field(row, "value")
        if raw_val is None or str(raw_val).strip() == "":
            batch.warnings.append(
                NormalizationWarning(
                    f"{entity_id}:{canon_metric}",
                    "missing_value",
                    f"Value for '{canon_metric}' on '{entity_id}' is empty/missing. Not coerced to zero.",
                    None,
                )
            )
            return

        raw_unit = self._field(row, "unit")
        val, unit, val_warns = normalize_metric_value_and_unit(
            canon_metric, raw_val, self._profile_unit(raw_metric, raw_unit)
        )
        for w in val_warns:
            batch.warnings.append(NormalizationWarning(f"{entity_id}:{canon_metric}", "value_quality", w, raw_val))

        if val is not None and unit is not None:
            obs = MetricObservation(
                observation_id=generate_id("OBS"),
                incident_id=batch.incident_id,
                source=default_source,
                entity_id=entity_id,
                metric_name=canon_metric,
                value=val,
                unit=unit,
                timestamp=ts,
                raw_reference={"row_index": row_idx, "raw_row": row},
            )
            batch.observations.append(obs)

    def _parse_wide_csv_row(
        self,
        row: dict[str, Any],
        row_idx: int,
        batch: IngestionBatchResult,
        default_source: str,
    ) -> None:
        raw_dev = self._field(row, "entity_id") or ""
        res = self.alias_resolver.resolve(raw_dev)
        entity_id = res.canonical_id
        if res.warning:
            batch.warnings.append(NormalizationWarning(entity_id, "alias_warning", res.warning, raw_dev))

        raw_ts = self._field(row, "timestamp")
        ts, ts_warn = normalize_timestamp(raw_ts)
        if ts_warn:
            batch.warnings.append(NormalizationWarning(entity_id, "timestamp_warning", ts_warn, raw_ts))
        if ts is None:
            batch.quarantined_records.append({"row_index": row_idx, "row": row, "error": "Missing timestamp"})
            return

        # Any column other than device/timestamp is treated as a metric
        reserved_cols = {
            name.casefold()
            for field_name in ("entity_id", "timestamp", "incident_id", "source_id")
            for name in self._field_candidates(field_name)
        }
        for col_name, raw_val in row.items():
            if not col_name or col_name.lower() in reserved_cols:
                continue

            if raw_val is None or str(raw_val).strip() == "":
                batch.warnings.append(
                    NormalizationWarning(
                        f"{entity_id}:{col_name}",
                        "missing_value",
                        f"Metric column '{col_name}' is empty. Not coerced to zero.",
                        None,
                    )
                )
                continue

            canon_metric, name_warn = self._metric_name(col_name)
            if name_warn:
                # Column is not a known canonical metric
                continue

            val, unit, val_warns = normalize_metric_value_and_unit(
                canon_metric, raw_val, self._profile_unit(col_name, None)
            )
            for w in val_warns:
                batch.warnings.append(NormalizationWarning(f"{entity_id}:{canon_metric}", "value_quality", w, raw_val))

            if val is not None and unit is not None:
                obs = MetricObservation(
                    observation_id=generate_id("OBS"),
                    incident_id=batch.incident_id,
                    source=default_source,
                    entity_id=entity_id,
                    metric_name=canon_metric,
                    value=val,
                    unit=unit,
                    timestamp=ts,
                    raw_reference={"row_index": row_idx, "column": col_name, "raw_val": raw_val},
                )
                batch.observations.append(obs)

    # ---------------- JSONL Logs Loader ----------------
    def load_jsonl(
        self,
        file_path: str | Path,
        incident_id: str = "INC-AUTO",
        default_source: str = "telemetry/logs",
    ) -> IngestionBatchResult:
        result = IngestionBatchResult(incident_id=incident_id)

        with open(file_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f):
                line_str = line.strip()
                if not line_str:
                    continue

                try:
                    record = json.loads(line_str)
                    if not isinstance(record, dict):
                        raise ValueError("JSONL line must be a JSON object.")

                    # Check if explicit observation contract
                    if "observation_type" in record:
                        obs_type = record["observation_type"]
                        if obs_type == "log":
                            result.observations.append(LogObservation.model_validate(record))
                        elif obs_type == "metric":
                            result.observations.append(MetricObservation.model_validate(record))
                        elif obs_type == "topology":
                            result.observations.append(TopologyObservation.model_validate(record))
                        elif obs_type == "config":
                            result.observations.append(ConfigObservation.model_validate(record))
                        continue

                    raw_dev = self._field(record, "entity_id") or "UNKNOWN"
                    res = self.alias_resolver.resolve(raw_dev)
                    raw_ts = self._field(record, "timestamp")
                    ts, timestamp_warning = normalize_timestamp(raw_ts)
                    if ts is None:
                        result.quarantined_records.append({
                            "line_index": line_idx,
                            "raw": record,
                            "error": "Missing or unparseable timestamp; record quarantined.",
                        })
                        result.warnings.append(NormalizationWarning(
                            record_id=str(record.get("observation_id", f"line-{line_idx}")),
                            warning_type="timestamp_error",
                            message="Missing or unparseable timestamp; record quarantined.",
                            raw_value=raw_ts,
                        ))
                        continue
                    if timestamp_warning:
                        result.warnings.append(NormalizationWarning(
                            record_id=str(record.get("observation_id", f"line-{line_idx}")),
                            warning_type="timestamp_warning",
                            message=timestamp_warning,
                            raw_value=raw_ts,
                        ))

                    # Check if metric event
                    raw_metric = self._field(record, "metric")
                    raw_value = self._field(record, "value")
                    if raw_metric and raw_value is not None:
                        canon_metric, name_warn = self._metric_name(raw_metric)
                        if not canon_metric:
                            result.quarantined_records.append({
                                "line_index": line_idx,
                                "raw": record,
                                "error": name_warn or f"Unmapped metric {raw_metric!r}",
                            })
                            result.warnings.append(NormalizationWarning(
                                record_id=str(record.get("observation_id", f"line-{line_idx}")),
                                warning_type="unmapped_metric",
                                message=name_warn or f"Unmapped metric {raw_metric!r}",
                                raw_value=raw_metric,
                            ))
                            continue
                        if canon_metric:
                            val, unit, unit_warnings = normalize_metric_value_and_unit(
                                canon_metric, raw_value,
                                self._profile_unit(raw_metric, self._field(record, "unit")),
                            )
                            for warning in unit_warnings:
                                result.warnings.append(NormalizationWarning(
                                    record_id=str(record.get("observation_id", f"line-{line_idx}")),
                                    warning_type="value_quality",
                                    message=warning,
                                    raw_value=raw_value,
                                ))
                            if val is not None and unit is not None:
                                metric_obs = MetricObservation(
                                    observation_id=generate_id("OBS"),
                                    incident_id=self._field(record, "incident_id") or incident_id,
                                    source=self._field(record, "source_id") or default_source,
                                    entity_id=res.canonical_id,
                                    metric_name=canon_metric,
                                    value=val,
                                    unit=unit,
                                    timestamp=ts,
                                    raw_reference={"line_index": line_idx, "raw_record": record},
                                )
                                result.observations.append(metric_obs)
                                continue
                            result.quarantined_records.append({
                                "line_index": line_idx,
                                "raw": record,
                                "error": "Metric value or unit could not be normalized.",
                            })
                            continue

                    # Otherwise normalize structured log record
                    log_obs = LogObservation(
                        observation_id=generate_id("OBS"),
                        incident_id=self._field(record, "incident_id") or incident_id,
                        source=self._field(record, "source_id") or default_source,
                        entity_id=res.canonical_id,
                        log_level=str(self._field(record, "log_level") or "INFO").upper(),
                        message=str(self._field(record, "message") or ""),
                        facility=self._field(record, "facility"),
                        timestamp=ts,
                        raw_reference={"line_index": line_idx, "raw_log": record},
                    )
                    result.observations.append(log_obs)
                except Exception as exc:
                    result.quarantined_records.append({"line_index": line_idx, "line": line_str, "error": str(exc)})

        return result
