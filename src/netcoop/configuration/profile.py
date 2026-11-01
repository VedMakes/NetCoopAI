"""Versioned, validated network profiles for adapting source data to NetCoop."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from netcoop.communication.vocabulary import get_metric_definition


class ProfileError(ValueError):
    """Raised when a profile cannot be loaded or would create unsafe mappings."""


class MetricMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    source_unit: str | None = None
    counter_semantics: Literal["gauge", "interval_count", "cumulative_counter"] = "gauge"


class NetworkProfile(BaseModel):
    """Network-specific names and policy separated from general diagnosis logic."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    version: str = "1.0"
    display_name: str
    source_fields: dict[str, str | list[str]] = Field(default_factory=dict)
    entity_aliases: dict[str, str] = Field(default_factory=dict)
    metric_mappings: dict[str, MetricMapping] = Field(default_factory=dict)
    entity_roles: dict[str, list[str]] = Field(default_factory=dict)
    topology_anchors: list[str] = Field(default_factory=list)
    relationship_aliases: dict[str, str] = Field(default_factory=dict)
    logical_relationships: list[str] = Field(default_factory=lambda: [
        "dns", "dhcp", "default_gateway", "uplink", "wireless_access"
    ])
    topology_completeness: Literal["complete", "partial", "unknown"] = "unknown"
    rule_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mappings(self) -> NetworkProfile:
        supported_source_fields = {
            "entity_id", "timestamp", "metric", "value", "unit",
            "incident_id", "source_id", "metrics", "message", "log_level", "facility",
            "source_entity", "target_entity", "relationship_type", "link_id",
            "capacity_mbps", "interface_name", "consumer_entity", "provider_entity",
        }
        unknown_fields = set(self.source_fields) - supported_source_fields
        if unknown_fields:
            raise ValueError(f"Unsupported source_fields keys: {sorted(unknown_fields)}")
        for field_name, configured in self.source_fields.items():
            candidates = [configured] if isinstance(configured, str) else configured
            if not candidates or any(not item.strip() for item in candidates):
                raise ValueError(f"source_fields.{field_name} requires non-empty field names")
            normalized = [item.strip().casefold() for item in candidates]
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"source_fields.{field_name} contains duplicate field names")

        alias_owners: dict[str, str] = {}
        for alias, canonical in self.entity_aliases.items():
            key = alias.strip().casefold()
            if not key or not canonical.strip():
                raise ValueError("entity_aliases requires non-empty alias and canonical ID")
            prior = alias_owners.get(key)
            if prior is not None and prior != canonical:
                raise ValueError(f"Ambiguous entity alias {alias!r} maps to both {prior!r} and {canonical!r}")
            alias_owners[key] = canonical

        metric_owners: dict[str, str] = {}
        for source_name, mapping in self.metric_mappings.items():
            if not source_name.strip():
                raise ValueError("metric_mappings cannot contain an empty source metric name")
            metric_key = source_name.strip().casefold()
            prior_metric = metric_owners.get(metric_key)
            if prior_metric is not None and prior_metric != mapping.canonical_name:
                raise ValueError(
                    f"Ambiguous source metric {source_name!r} maps to both "
                    f"{prior_metric!r} and {mapping.canonical_name!r}"
                )
            metric_owners[metric_key] = mapping.canonical_name
            if get_metric_definition(mapping.canonical_name) is None:
                raise ValueError(
                    f"Metric mapping {source_name!r} targets unsupported canonical metric "
                    f"{mapping.canonical_name!r}"
                )
            expected = get_metric_definition(mapping.canonical_name).get("unit")
            unit = mapping.source_unit.strip().casefold() if mapping.source_unit else None
            accepted = {
                "percent": {"%", "pct", "percent", "percentage", "fraction", "ratio", "decimal"},
                "milliseconds": {"ms", "milliseconds", "msec", "s", "sec", "seconds", "us", "usec", "microseconds"},
                "mbps": {"mbps", "mb/s", "megabits/sec", "kbps", "kb/s", "kilobits/sec", "gbps", "gb/s", "gigabits/sec", "bps", "bits/sec", "bytes/sec", "b/s"},
                "count": {"count", "packets", "drops", "errors", "flaps", "pkts", "frames"},
                "dbm": {"dbm", "db", "decibel", "decibels"},
                "db": {"db", "dbm", "decibel", "decibels"},
            }.get(expected)
            if unit and accepted is not None and unit not in accepted:
                raise ValueError(
                    f"Metric mapping {source_name!r} has incompatible source_unit {mapping.source_unit!r} "
                    f"for {mapping.canonical_name!r} ({expected})"
                )
            if mapping.counter_semantics in {"interval_count", "cumulative_counter"} and expected != "count":
                raise ValueError(
                    f"Metric mapping {source_name!r} declares counter semantics but targets "
                    f"non-count metric {mapping.canonical_name!r}"
                )
        canonical_anchors = [self.canonical_entity(entity) for entity in self.topology_anchors]
        if len(canonical_anchors) != len(set(canonical_anchors)):
            raise ValueError("topology_anchors must be unique")
        return self

    @classmethod
    def load(cls, path: str | Path) -> NetworkProfile:
        profile_path = Path(path)
        try:
            raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ProfileError("Profile root must be a YAML mapping")
            profile = cls.model_validate(raw)
        except ProfileError:
            raise
        except Exception as exc:
            raise ProfileError(f"Invalid network profile {profile_path}: {exc}") from exc
        if profile.version != "1.0":
            raise ProfileError(f"Unsupported profile version {profile.version!r}; supported version is '1.0'")
        return profile

    def aliases(self) -> dict[str, str]:
        """Return aliases with case-insensitive duplicate keys normalized."""
        return {alias.strip().upper(): canonical.strip() for alias, canonical in self.entity_aliases.items()}

    def map_metric(self, source_name: str) -> MetricMapping | None:
        key = source_name.strip().casefold()
        return next((value for name, value in self.metric_mappings.items() if name.strip().casefold() == key), None)

    def canonical_entity(self, entity_id: str) -> str:
        key = entity_id.strip().upper()
        return self.aliases().get(key, entity_id.strip())

    def canonical_relationship(self, relationship: str) -> str:
        key = relationship.strip().casefold()
        return next(
            (value for alias, value in self.relationship_aliases.items()
             if alias.strip().casefold() == key),
            key,
        )

    def entities_for_role(self, role: str) -> set[str]:
        wanted = role.casefold()
        return {
            self.canonical_entity(entity)
            for entity, roles in self.entity_roles.items()
            if wanted in {item.casefold() for item in roles}
        }

    def apply_to_rules(self, base_rules: dict[str, Any]) -> dict[str, Any]:
        """Deep-merge known per-domain overrides and expose profile role metadata."""
        rules = deepcopy(base_rules)
        for section, overrides in self.rule_overrides.items():
            if section not in rules or not isinstance(rules[section], dict):
                raise ProfileError(f"Unknown rule section {section!r}")
            unknown = set(overrides) - set(rules[section])
            if unknown:
                raise ProfileError(f"Unknown rule(s) in {section}: {sorted(unknown)}")
            for key, value in overrides.items():
                original = rules[section][key]
                valid_type = (
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    if isinstance(original, (int, float)) and not isinstance(original, bool)
                    else isinstance(value, list) and all(isinstance(item, str) for item in value)
                    if isinstance(original, list)
                    else isinstance(value, type(original))
                )
                if not valid_type:
                    raise ProfileError(f"Rule {section}.{key} has incompatible value type")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if (key.endswith("_pct") and not 0 <= value <= 100) or value < 0:
                        raise ProfileError(f"Rule {section}.{key} is outside a valid range")
            rules[section].update(overrides)
        rules.setdefault("connectivity", {})["topology_anchors"] = [
            self.canonical_entity(entity) for entity in self.topology_anchors
        ]
        rules["connectivity"]["logical_relationships"] = [
            item.casefold() for item in self.logical_relationships
        ]
        rules["connectivity"]["topology_completeness"] = self.topology_completeness
        rules.setdefault("services", {})["entity_roles"] = {
            role: sorted(self.entities_for_role(role))
            for role in ("dns_resolver", "dhcp_server")
        }
        return rules

    def mapping_coverage(self, source_metric_names: set[str]) -> tuple[set[str], set[str]]:
        mapped = set()
        unmapped = set()
        for metric_name in source_metric_names:
            if self.map_metric(metric_name) is not None:
                mapped.add(metric_name)
            else:
                unmapped.add(metric_name)
        return mapped, unmapped

    def source_field_candidates(self, canonical_field: str) -> list[str]:
        """Return configured source field names followed by common format aliases."""
        configured = self.source_fields.get(canonical_field, [])
        names = [configured.strip()] if isinstance(configured, str) else [item.strip() for item in configured]
        defaults = {
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
            "relationship_type": ["relationship_type", "link_type", "dependency_type", "type"],
            "link_id": ["link_id", "id"],
            "capacity_mbps": ["capacity_mbps", "speed_mbps", "capacity"],
            "interface_name": ["interface_name", "source_interface", "interface"],
            "consumer_entity": ["consumer_entity", "consumer", "client"],
            "provider_entity": ["provider_entity", "provider", "server"],
        }.get(canonical_field, [])
        ordered: list[str] = []
        for name in [*names, *defaults]:
            if name not in ordered:
                ordered.append(name)
        return ordered
