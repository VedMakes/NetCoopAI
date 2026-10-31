#!/usr/bin/env python3
"""NetCoop AI Synthetic Network Data Generator.

Generates realistic, reproducible, multi-step synthetic campus network telemetry,
network topology, and isolated ground truth following the NetCoop AI architecture.

Pipeline:
Scenario configuration -> Network simulator -> Raw telemetry + topology + hidden ground truth
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Canonical schema version
SCHEMA_VERSION = "1.0"

# Default simulation anchor time (deterministic, timezone-aware UTC)
DEFAULT_SIM_START_TIME = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# 1. Topology Contracts
# =============================================================================


@dataclass(frozen=True)
class TopologyNode:
    entity_id: str
    entity_type: str  # device, access_point, service, hostel_zone
    role: str
    name: str


@dataclass(frozen=True)
class TopologyInterface:
    interface_id: str
    device_id: str
    speed_mbps: float


@dataclass(frozen=True)
class TopologyLink:
    link_id: str
    source_entity: str
    target_entity: str
    source_interface: str
    target_interface: str
    capacity_mbps: float
    link_type: str  # ethernet, wireless, trunk


@dataclass(frozen=True)
class ServiceDependency:
    consumer_entity: str
    provider_entity: str
    dependency_type: str  # dns, dhcp, default_gateway, uplink


@dataclass
class TopologyConfig:
    topology_id: str
    schema_version: str
    nodes: list[TopologyNode]
    interfaces: list[TopologyInterface]
    links: list[TopologyLink]
    service_dependencies: list[ServiceDependency]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology_id": self.topology_id,
            "schema_version": self.schema_version,
            "nodes": [asdict(n) for n in self.nodes],
            "interfaces": [asdict(i) for i in self.interfaces],
            "links": [asdict(lnk) for lnk in self.links],
            "service_dependencies": [asdict(d) for d in self.service_dependencies],
        }


def build_default_campus_topology() -> TopologyConfig:
    """Builds a consistent 10-node campus network topology.

    Hierarchy:
    Edge Gateway -> Core Switch -> Distribution Switches (Hostel / Dept) -> APs / Access Switches -> Endpoints & Services
    """
    nodes = [
        TopologyNode("GW_EDGE_01", "device", "gateway", "Campus Edge Gateway"),
        TopologyNode("SW_CORE_01", "device", "core_switch", "Campus Core Backbone Switch"),
        TopologyNode("SW_DIST_HOSTEL", "device", "distribution_switch", "Hostel Distribution Switch"),
        TopologyNode("SW_DIST_DEPT", "device", "distribution_switch", "Academic Department Switch"),
        TopologyNode("SW_ACCESS_LAB", "device", "access_switch", "Computing Lab Access Switch"),
        TopologyNode("AP_HOSTEL_A", "access_point", "wireless_ap", "Hostel Block A Access Point"),
        TopologyNode("AP_HOSTEL_B", "access_point", "wireless_ap", "Hostel Block B Access Point"),
        TopologyNode("SRV_DNS_01", "service", "dns_server", "Campus Recursive DNS Server"),
        TopologyNode("SRV_DHCP_01", "service", "dhcp_server", "Campus Central DHCP Server"),
        TopologyNode("HOSTEL_ZONE_A", "hostel_zone", "client_segment", "Hostel Block A Student Segment"),
    ]

    interfaces = [
        TopologyInterface("GW_EDGE_01:eth0", "GW_EDGE_01", 10000.0),
        TopologyInterface("GW_EDGE_01:eth1", "GW_EDGE_01", 10000.0),
        TopologyInterface("SW_CORE_01:Gi0/1", "SW_CORE_01", 10000.0),
        TopologyInterface("SW_CORE_01:Gi0/2", "SW_CORE_01", 1000.0),
        TopologyInterface("SW_CORE_01:Gi0/3", "SW_CORE_01", 1000.0),
        TopologyInterface("SW_CORE_01:Gi0/4", "SW_CORE_01", 1000.0),
        TopologyInterface("SW_CORE_01:Gi0/5", "SW_CORE_01", 1000.0),
        TopologyInterface("SW_DIST_HOSTEL:uplink", "SW_DIST_HOSTEL", 1000.0),
        TopologyInterface("SW_DIST_HOSTEL:Gi0/1", "SW_DIST_HOSTEL", 1000.0),
        TopologyInterface("SW_DIST_HOSTEL:Gi0/2", "SW_DIST_HOSTEL", 1000.0),
        TopologyInterface("SW_DIST_DEPT:uplink", "SW_DIST_DEPT", 1000.0),
        TopologyInterface("SW_DIST_DEPT:Gi0/1", "SW_DIST_DEPT", 1000.0),
        TopologyInterface("SW_ACCESS_LAB:uplink", "SW_ACCESS_LAB", 1000.0),
        TopologyInterface("AP_HOSTEL_A:eth0", "AP_HOSTEL_A", 1000.0),
        TopologyInterface("AP_HOSTEL_A:wlan0", "AP_HOSTEL_A", 300.0),
        TopologyInterface("AP_HOSTEL_B:eth0", "AP_HOSTEL_B", 1000.0),
        TopologyInterface("SRV_DNS_01:eth0", "SRV_DNS_01", 1000.0),
        TopologyInterface("SRV_DHCP_01:eth0", "SRV_DHCP_01", 1000.0),
    ]

    links = [
        TopologyLink("LINK_CORE_GW", "SW_CORE_01", "GW_EDGE_01", "SW_CORE_01:Gi0/1", "GW_EDGE_01:eth1", 10000.0, "trunk"),
        TopologyLink("LINK_CORE_HOSTEL", "SW_CORE_01", "SW_DIST_HOSTEL", "SW_CORE_01:Gi0/2", "SW_DIST_HOSTEL:uplink", 1000.0, "ethernet"),
        TopologyLink("LINK_CORE_DEPT", "SW_CORE_01", "SW_DIST_DEPT", "SW_CORE_01:Gi0/3", "SW_DIST_DEPT:uplink", 1000.0, "ethernet"),
        TopologyLink("LINK_CORE_DNS", "SW_CORE_01", "SRV_DNS_01", "SW_CORE_01:Gi0/4", "SRV_DNS_01:eth0", 1000.0, "ethernet"),
        TopologyLink("LINK_CORE_DHCP", "SW_CORE_01", "SRV_DHCP_01", "SW_CORE_01:Gi0/5", "SRV_DHCP_01:eth0", 1000.0, "ethernet"),
        TopologyLink("LINK_HOSTEL_AP_A", "SW_DIST_HOSTEL", "AP_HOSTEL_A", "SW_DIST_HOSTEL:Gi0/1", "AP_HOSTEL_A:eth0", 1000.0, "ethernet"),
        TopologyLink("LINK_HOSTEL_AP_B", "SW_DIST_HOSTEL", "AP_HOSTEL_B", "SW_DIST_HOSTEL:Gi0/2", "AP_HOSTEL_B:eth0", 1000.0, "ethernet"),
        TopologyLink("LINK_DEPT_LAB", "SW_DIST_DEPT", "SW_ACCESS_LAB", "SW_DIST_DEPT:Gi0/1", "SW_ACCESS_LAB:uplink", 1000.0, "ethernet"),
        TopologyLink("LINK_WIFI_ZONE_A", "AP_HOSTEL_A", "HOSTEL_ZONE_A", "AP_HOSTEL_A:wlan0", "HOSTEL_ZONE_A:wlan", 300.0, "wireless"),
    ]

    dependencies = [
        ServiceDependency("HOSTEL_ZONE_A", "AP_HOSTEL_A", "wireless_access"),
        ServiceDependency("AP_HOSTEL_A", "SW_DIST_HOSTEL", "uplink"),
        ServiceDependency("SW_DIST_HOSTEL", "SW_CORE_01", "uplink"),
        ServiceDependency("SW_DIST_DEPT", "SW_CORE_01", "uplink"),
        ServiceDependency("SW_CORE_01", "GW_EDGE_01", "default_gateway"),
        ServiceDependency("HOSTEL_ZONE_A", "SRV_DNS_01", "dns"),
        ServiceDependency("HOSTEL_ZONE_A", "SRV_DHCP_01", "dhcp"),
    ]

    return TopologyConfig(
        topology_id="TOPO-IIT-CAMPUS-01",
        schema_version=SCHEMA_VERSION,
        nodes=nodes,
        interfaces=interfaces,
        links=links,
        service_dependencies=dependencies,
    )


# =============================================================================
# 2. Simulation & Fault Configuration Contracts
# =============================================================================


@dataclass(frozen=True)
class FaultConfig:
    fault_class: str  # healthy, link_congestion, weak_wifi, interface_fault, device_overload, dns_failure, dhcp_failure
    target_entity: str
    start_step: int
    duration_steps: int
    severity: str
    intended_affected_entities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    incident_id: str
    fault_config: FaultConfig
    seed: int = 42
    num_steps: int = 15
    sampling_interval_seconds: int = 30
    start_time: datetime = DEFAULT_SIM_START_TIME


@dataclass(frozen=True)
class TelemetryObservation:
    incident_id: str
    event_time: str
    entity_id: str
    entity_type: str
    source_id: str
    metric: str
    value: float
    unit: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GroundTruth:
    scenario_id: str
    incident_id: str
    injected_fault_class: str
    target_entity: str
    intended_affected_entities: list[str]
    fault_start_step: int
    fault_start_time: str
    fault_duration_steps: int
    severity: str
    simulator_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Predefined scenario specifications
SCENARIO_PRESETS: dict[str, FaultConfig] = {
    "healthy": FaultConfig(
        fault_class="healthy",
        target_entity="none",
        start_step=0,
        duration_steps=0,
        severity="none",
        intended_affected_entities=[],
    ),
    "link_congestion": FaultConfig(
        fault_class="link_congestion",
        target_entity="SW_CORE_01:Gi0/2",
        start_step=4,
        duration_steps=8,
        severity="high",
        intended_affected_entities=["SW_CORE_01:Gi0/2", "SW_DIST_HOSTEL", "AP_HOSTEL_A", "HOSTEL_ZONE_A"],
    ),
    "weak_wifi": FaultConfig(
        fault_class="weak_wifi",
        target_entity="AP_HOSTEL_A",
        start_step=4,
        duration_steps=8,
        severity="medium",
        intended_affected_entities=["AP_HOSTEL_A", "HOSTEL_ZONE_A"],
    ),
    "interface_fault": FaultConfig(
        fault_class="interface_fault",
        target_entity="SW_DIST_DEPT:Gi0/1",
        start_step=4,
        duration_steps=8,
        severity="high",
        intended_affected_entities=["SW_DIST_DEPT:Gi0/1", "SW_ACCESS_LAB"],
    ),
    "device_overload": FaultConfig(
        fault_class="device_overload",
        target_entity="SW_CORE_01",
        start_step=4,
        duration_steps=8,
        severity="critical",
        intended_affected_entities=["SW_CORE_01", "SW_DIST_HOSTEL", "SW_DIST_DEPT"],
    ),
    "dns_failure": FaultConfig(
        fault_class="dns_failure",
        target_entity="SRV_DNS_01",
        start_step=4,
        duration_steps=8,
        severity="high",
        intended_affected_entities=["SRV_DNS_01", "HOSTEL_ZONE_A"],
    ),
    "dhcp_failure": FaultConfig(
        fault_class="dhcp_failure",
        target_entity="SRV_DHCP_01",
        start_step=4,
        duration_steps=8,
        severity="high",
        intended_affected_entities=["SRV_DHCP_01", "HOSTEL_ZONE_A"],
    ),
}


# =============================================================================
# 3. Network Simulator Implementation
# =============================================================================


class NetworkSimulator:
    """Stateful, deterministic network simulator emitting observable telemetry."""

    def __init__(
        self,
        scenario_config: ScenarioConfig,
        topology: TopologyConfig | None = None,
    ) -> None:
        self.config = scenario_config
        self.topology = topology or build_default_campus_topology()
        # Seeded random generator guaranteeing exact reproducibility
        self.rng = random.Random(self.config.seed)

    def run(self) -> tuple[list[TelemetryObservation], TopologyConfig, GroundTruth]:
        """Runs the simulation over the configured steps and produces telemetry, topology, and ground truth."""
        observations: list[TelemetryObservation] = []
        fault = self.config.fault_config

        fault_start_time_iso = (
            self.config.start_time
            + timedelta(seconds=fault.start_step * self.config.sampling_interval_seconds)
        ).isoformat()

        ground_truth = GroundTruth(
            scenario_id=self.config.scenario_id,
            incident_id=self.config.incident_id,
            injected_fault_class=fault.fault_class,
            target_entity=fault.target_entity,
            intended_affected_entities=fault.intended_affected_entities,
            fault_start_step=fault.start_step,
            fault_start_time=fault_start_time_iso,
            fault_duration_steps=fault.duration_steps,
            severity=fault.severity,
            simulator_metadata={
                "seed": self.config.seed,
                "num_steps": self.config.num_steps,
                "sampling_interval_seconds": self.config.sampling_interval_seconds,
                "start_time": self.config.start_time.isoformat(),
            },
        )

        for step in range(self.config.num_steps):
            step_time = self.config.start_time + timedelta(
                seconds=step * self.config.sampling_interval_seconds
            )
            time_str = step_time.isoformat()

            # Check if fault is currently active
            is_fault_active = (
                fault.fault_class != "healthy"
                and fault.start_step <= step < (fault.start_step + fault.duration_steps)
            )

            # 1. Device metrics (CPU, Memory)
            self._simulate_devices(step, time_str, is_fault_active, observations)

            # 2. Interface and Link metrics (Utilization, Drops, Latency, Loss, Errors)
            self._simulate_interfaces_and_links(step, time_str, is_fault_active, observations)

            # 3. Wireless Access Point metrics (RSSI, SNR, Retransmissions)
            self._simulate_wireless(step, time_str, is_fault_active, observations)

            # 4. Service metrics (DNS & DHCP)
            self._simulate_services(step, time_str, is_fault_active, observations)

        return observations, self.topology, ground_truth

    def _simulate_devices(
        self,
        step: int,
        time_str: str,
        is_fault_active: bool,
        obs: list[TelemetryObservation],
    ) -> None:
        fault = self.config.fault_config
        for node in self.topology.nodes:
            if node.entity_type != "device":
                continue

            cpu_val = round(self.rng.uniform(18.0, 32.0), 2)
            mem_val = round(self.rng.uniform(35.0, 48.0), 2)

            if is_fault_active and fault.fault_class == "device_overload" and node.entity_id == fault.target_entity:
                # Spike CPU and memory under device overload fault
                cpu_val = round(self.rng.uniform(96.0, 99.8), 2)
                mem_val = round(self.rng.uniform(88.0, 94.0), 2)

            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=node.entity_id,
                    entity_type="device",
                    source_id="collector/snmp",
                    metric="cpu_utilization_pct",
                    value=cpu_val,
                    unit="percent",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=node.entity_id,
                    entity_type="device",
                    source_id="collector/snmp",
                    metric="memory_utilization_pct",
                    value=mem_val,
                    unit="percent",
                )
            )

    def _simulate_interfaces_and_links(
        self,
        step: int,
        time_str: str,
        is_fault_active: bool,
        obs: list[TelemetryObservation],
    ) -> None:
        fault = self.config.fault_config
        for link in self.topology.links:
            util_val = round(self.rng.uniform(22.0, 42.0), 2)
            queue_drops = 0
            loss_pct = 0.0
            latency = round(self.rng.uniform(4.0, 12.0), 2)
            jitter = round(self.rng.uniform(1.0, 3.5), 2)
            errors = 0

            # Fault: Link congestion on target interface
            if is_fault_active and fault.fault_class == "link_congestion":
                if link.source_interface == fault.target_entity or link.target_interface == fault.target_entity:
                    util_val = round(self.rng.uniform(93.0, 98.5), 2)
                    queue_drops = self.rng.randint(120, 450)
                    loss_pct = round(self.rng.uniform(1.2, 3.8), 2)
                    latency = round(self.rng.uniform(210.0, 320.0), 2)
                    jitter = round(self.rng.uniform(25.0, 45.0), 2)

            # Fault: Interface degradation (CRC / errors / drops)
            elif is_fault_active and fault.fault_class == "interface_fault":
                if link.source_interface == fault.target_entity or link.target_interface == fault.target_entity:
                    errors = self.rng.randint(45, 180)
                    loss_pct = round(self.rng.uniform(2.5, 5.5), 2)
                    latency = round(self.rng.uniform(35.0, 85.0), 2)

            # Fault: Device overload causes downstream queuing delay and transit drops
            elif is_fault_active and fault.fault_class == "device_overload":
                if link.source_entity == fault.target_entity:
                    latency = round(self.rng.uniform(140.0, 260.0), 2)
                    queue_drops = self.rng.randint(30, 110)

            # Emit interface telemetry for the source interface
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=link.source_interface,
                    entity_type="interface",
                    source_id="collector/telemetry",
                    metric="link_utilization_pct",
                    value=util_val,
                    unit="percent",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=link.source_interface,
                    entity_type="interface",
                    source_id="collector/telemetry",
                    metric="queue_drops",
                    value=float(queue_drops),
                    unit="count",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=link.source_interface,
                    entity_type="interface",
                    source_id="collector/telemetry",
                    metric="packet_loss_pct",
                    value=loss_pct,
                    unit="percent",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=link.source_interface,
                    entity_type="interface",
                    source_id="collector/telemetry",
                    metric="latency_ms",
                    value=latency,
                    unit="milliseconds",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=link.source_interface,
                    entity_type="interface",
                    source_id="collector/telemetry",
                    metric="jitter_ms",
                    value=jitter,
                    unit="milliseconds",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=link.source_interface,
                    entity_type="interface",
                    source_id="collector/telemetry",
                    metric="interface_errors",
                    value=float(errors),
                    unit="count",
                )
            )

    def _simulate_wireless(
        self,
        step: int,
        time_str: str,
        is_fault_active: bool,
        obs: list[TelemetryObservation],
    ) -> None:
        fault = self.config.fault_config
        for node in self.topology.nodes:
            if node.entity_type != "access_point":
                continue

            rssi = round(self.rng.uniform(-62.0, -56.0), 2)
            snr = round(self.rng.uniform(32.0, 38.0), 2)
            throughput = round(self.rng.uniform(140.0, 210.0), 2)
            loss_pct = 0.0

            if is_fault_active and fault.fault_class == "weak_wifi" and node.entity_id == fault.target_entity:
                # Severe signal degradation
                rssi = round(self.rng.uniform(-86.0, -81.0), 2)
                snr = round(self.rng.uniform(9.0, 14.0), 2)
                throughput = round(self.rng.uniform(6.0, 18.0), 2)
                loss_pct = round(self.rng.uniform(4.5, 9.0), 2)

            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=node.entity_id,
                    entity_type="access_point",
                    source_id="collector/wifi",
                    metric="rssi_dbm",
                    value=rssi,
                    unit="dbm",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=node.entity_id,
                    entity_type="access_point",
                    source_id="collector/wifi",
                    metric="snr_db",
                    value=snr,
                    unit="db",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=node.entity_id,
                    entity_type="access_point",
                    source_id="collector/wifi",
                    metric="throughput_mbps",
                    value=throughput,
                    unit="mbps",
                )
            )
            obs.append(
                TelemetryObservation(
                    incident_id=self.config.incident_id,
                    event_time=time_str,
                    entity_id=node.entity_id,
                    entity_type="access_point",
                    source_id="collector/wifi",
                    metric="packet_loss_pct",
                    value=loss_pct,
                    unit="percent",
                )
            )

    def _simulate_services(
        self,
        step: int,
        time_str: str,
        is_fault_active: bool,
        obs: list[TelemetryObservation],
    ) -> None:
        fault = self.config.fault_config

        # 1. DNS Service
        dns_lat = round(self.rng.uniform(2.0, 6.0), 2)
        dns_loss = 0.0
        if is_fault_active and fault.fault_class == "dns_failure":
            dns_lat = round(self.rng.uniform(2200.0, 3500.0), 2)
            dns_loss = round(self.rng.uniform(85.0, 100.0), 2)

        obs.append(
            TelemetryObservation(
                incident_id=self.config.incident_id,
                event_time=time_str,
                entity_id="SRV_DNS_01",
                entity_type="service",
                source_id="collector/synthetic_probe",
                metric="latency_ms",
                value=dns_lat,
                unit="milliseconds",
            )
        )
        obs.append(
            TelemetryObservation(
                incident_id=self.config.incident_id,
                event_time=time_str,
                entity_id="SRV_DNS_01",
                entity_type="service",
                source_id="collector/synthetic_probe",
                metric="packet_loss_pct",
                value=dns_loss,
                unit="percent",
            )
        )

        # 2. DHCP Service
        dhcp_lat = round(self.rng.uniform(5.0, 12.0), 2)
        dhcp_loss = 0.0
        if is_fault_active and fault.fault_class == "dhcp_failure":
            dhcp_lat = round(self.rng.uniform(2800.0, 4200.0), 2)
            dhcp_loss = round(self.rng.uniform(90.0, 100.0), 2)

        obs.append(
            TelemetryObservation(
                incident_id=self.config.incident_id,
                event_time=time_str,
                entity_id="SRV_DHCP_01",
                entity_type="service",
                source_id="collector/synthetic_probe",
                metric="latency_ms",
                value=dhcp_lat,
                unit="milliseconds",
            )
        )
        obs.append(
            TelemetryObservation(
                incident_id=self.config.incident_id,
                event_time=time_str,
                entity_id="SRV_DHCP_01",
                entity_type="service",
                source_id="collector/synthetic_probe",
                metric="packet_loss_pct",
                value=dhcp_loss,
                unit="percent",
            )
        )


# =============================================================================
# 4. Scenario Generation and Artifact Writing
# =============================================================================


def generate_scenario(
    scenario_name: str,
    output_dir: Path | str,
    seed: int = 42,
    num_steps: int = 15,
    sampling_interval_seconds: int = 30,
    start_time: datetime = DEFAULT_SIM_START_TIME,
) -> dict[str, Path]:
    """Generates a scenario and writes the three strictly separated artifacts:

    1. <output_dir>/telemetry.jsonl      (observable metrics, no answers)
    2. <output_dir>/topology.json       (network structure)
    3. <output_dir>/evaluation/ground_truth.json (evaluation-only ground truth)
    """
    if scenario_name not in SCENARIO_PRESETS:
        raise ValueError(
            f"Unknown scenario '{scenario_name}'. Available: {list(SCENARIO_PRESETS.keys())}"
        )

    fault_cfg = SCENARIO_PRESETS[scenario_name]
    scenario_id = f"SCEN-{scenario_name.upper()}-01"
    incident_id = f"INC-SYNTH-{scenario_name.upper()[:4]}-001"

    config = ScenarioConfig(
        scenario_id=scenario_id,
        incident_id=incident_id,
        fault_config=fault_cfg,
        seed=seed,
        num_steps=num_steps,
        sampling_interval_seconds=sampling_interval_seconds,
        start_time=start_time,
    )

    simulator = NetworkSimulator(config)
    observations, topology, ground_truth = simulator.run()

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry output (JSONL, observable only, no fault labels)
    telemetry_path = out_path / "telemetry.jsonl"
    with open(telemetry_path, "w", encoding="utf-8") as f:
        for obs in observations:
            f.write(json.dumps(obs.to_dict()) + "\n")

    # 2. Topology output (JSON, network structure only)
    topology_path = out_path / "topology.json"
    with open(topology_path, "w", encoding="utf-8") as f:
        json.dump(topology.to_dict(), f, indent=2)

    # 3. Ground truth output (Strictly isolated in evaluation/ directory)
    eval_dir = out_path / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_path = eval_dir / "ground_truth.json"
    with open(ground_truth_path, "w", encoding="utf-8") as f:
        json.dump(ground_truth.to_dict(), f, indent=2)

    return {
        "telemetry": telemetry_path,
        "topology": topology_path,
        "ground_truth": ground_truth_path,
    }


def generate_all_scenarios(
    base_dir: Path | str = "data/scenarios",
    seed: int = 42,
    num_steps: int = 15,
) -> dict[str, dict[str, Path]]:
    """Generates all defined scenario presets into separate directories."""
    results: dict[str, dict[str, Path]] = {}
    base_path = Path(base_dir)
    for name in SCENARIO_PRESETS:
        scen_dir = base_path / name
        results[name] = generate_scenario(name, scen_dir, seed=seed, num_steps=num_steps)
    return results


# Backward compatibility shim
def generate_telemetry(fault_type: str = "healthy", seed: int = 42) -> dict[str, Any]:
    """Shim providing single-record output for backward compatibility."""
    mapped_scenario = "healthy"
    if fault_type in SCENARIO_PRESETS:
        mapped_scenario = fault_type
    elif fault_type in ("latency_spike", "congestion"):
        mapped_scenario = "link_congestion"
    elif fault_type in ("hardware_failure", "critical"):
        mapped_scenario = "device_overload"

    config = ScenarioConfig(
        scenario_id="SCEN-SHIM",
        incident_id="INC-SHIM",
        fault_config=SCENARIO_PRESETS[mapped_scenario],
        seed=seed,
        num_steps=1,
    )
    obs, _, _ = NetworkSimulator(config).run()
    if obs:
        return obs[0].to_dict()
    return {}


# =============================================================================
# 5. CLI Execution
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NetCoop AI Synthetic Campus Network Generator"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        choices=list(SCENARIO_PRESETS.keys()) + ["all"],
        help="Scenario class to generate (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/scenarios",
        help="Directory where scenario artifacts will be stored (default: data/scenarios)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=15,
        help="Number of simulation steps (default: 15)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Sampling interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit",
    )

    args = parser.parse_args()

    if args.list_scenarios:
        print("Available NetCoop AI Scenarios:")
        for name, cfg in SCENARIO_PRESETS.items():
            print(f"  - {name:18} (fault: {cfg.fault_class:16} target: {cfg.target_entity})")
        return

    if args.scenario == "all":
        print(f"Generating all scenarios into '{args.output_dir}' (seed={args.seed})...")
        results = generate_all_scenarios(
            base_dir=args.output_dir,
            seed=args.seed,
            num_steps=args.steps,
        )
        for name, paths in results.items():
            print(f"✓ {name}:")
            print(f"    telemetry:    {paths['telemetry']}")
            print(f"    topology:     {paths['topology']}")
            print(f"    ground truth: {paths['ground_truth']}")
    else:
        scen_dir = Path(args.output_dir) / args.scenario
        paths = generate_scenario(
            scenario_name=args.scenario,
            output_dir=scen_dir,
            seed=args.seed,
            num_steps=args.steps,
            sampling_interval_seconds=args.interval,
        )
        print(f"✓ Generated scenario '{args.scenario}':")
        print(f"    telemetry:    {paths['telemetry']}")
        print(f"    topology:     {paths['topology']}")
        print(f"    ground truth: {paths['ground_truth']}")


if __name__ == "__main__":
    main()
