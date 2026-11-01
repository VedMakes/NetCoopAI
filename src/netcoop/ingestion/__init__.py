"""Ingestion and normalization package for NetCoop AI."""

from netcoop.ingestion.aliases import AliasResolutionResult, EntityAliasResolver
from netcoop.ingestion.loaders import IngestionBatchResult, TelemetryLoader
from netcoop.ingestion.normalization import (
    NormalizationWarning,
    NormalizedMetricResult,
    normalize_metric_name,
    normalize_metric_value_and_unit,
    normalize_timestamp,
)

__all__ = [
    "AliasResolutionResult",
    "EntityAliasResolver",
    "IngestionBatchResult",
    "NormalizationWarning",
    "NormalizedMetricResult",
    "TelemetryLoader",
    "normalize_metric_name",
    "normalize_metric_value_and_unit",
    "normalize_timestamp",
]
