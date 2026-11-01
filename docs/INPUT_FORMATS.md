# Local data and topology inputs

The CLI reads files from the machine where it runs. Use `netcoop triage` with a telemetry file or capture directory, and optionally provide a network map. The browser dashboard accepts telemetry file contents and an optional topology JSON upload; it does not connect directly to network devices.

## Quick start with a capture directory

```text
office-capture/
├── telemetry.jsonl
└── topology.json       # optional
```

```bash
netcoop triage ./office-capture --site office-east \
  --symptom-chat "Wi-Fi drops in the second-floor meeting rooms"
```

The telemetry file can also be supplied directly. Supported telemetry inputs are JSON, JSONL, CSV, and `.log` files whose contents are JSON Lines (one JSON object per line). A `.log` suffix does not enable parsing arbitrary raw syslog text. A standalone map can be supplied with either `--sitemap` or `--topology`:

```bash
netcoop triage ./office-capture/telemetry.jsonl \
  --site office-east \
  --sitemap ./office-east-topology.json
```

An explicit sitemap replaces the capture directory's `topology.json`. If no explicit map is supplied, NetCoop checks `config/sites/<site>/topology.json` when a site is selected, then checks the capture directory. A matching `config/profiles/<site>.yaml` is loaded automatically; `--profile` selects a different profile explicitly.

## Telemetry records

NetCoop accepts canonical observation records and common flat telemetry exports. A JSONL metric record can look like:

```json
{"incident_id":"INC-101","event_time":"2026-10-30T09:00:00Z","entity_id":"AP-2F-03","source_id":"wifi-controller","metric":"rssi_dbm","value":-84,"unit":"dbm"}
```

Include a stable entity name, timestamp, metric name, value, and unit where available. Unknown metric names, missing timestamps, invalid units, and malformed rows are reported or quarantined; NetCoop will not invent missing measurements. For vendor-specific field names and known unit conversions, draft and review a site profile with `profile-init` and `profile-validate`. See [Network Profiles](NETWORK_PROFILES.md).

## Topology map format

Topology maps are JSON objects with a list of physical links. `service_dependencies` is optional and describes logical dependencies such as DNS or DHCP; it does not create a physical route.

```json
{
  "schema_version": "1.0",
  "nodes": [
    { "entity_id": "DNS-OFFICE-01", "name": "Office DNS", "role": "dns_resolver", "entity_type": "service" },
    { "entity_id": "SPARE-SW-01", "name": "Spare switch", "role": "access_switch" }
  ],
  "links": [
    {
      "link_id": "LINK-AP-TO-IDF",
      "source_entity": "AP-2F-03",
      "target_entity": "SW-IDF-2F",
      "relationship_type": "connected_to",
      "capacity_mbps": 2500,
      "interface_name": "Gi1/0/24"
    }
  ],
  "service_dependencies": [
    {
      "consumer_entity": "OFFICE-CLIENTS",
      "provider_entity": "DNS-OFFICE-01",
      "dependency_type": "dns"
    }
  ]
}
```

Each link needs `source_entity` and `target_entity`; a stable `link_id` is recommended so report references remain understandable. Source field names may be mapped in the site profile. `topology_completeness` belongs in the profile: use `complete` only when the map is intended to cover the whole site. For partial or unknown maps, an absent route is not treated as proof that devices cannot communicate.

The optional `nodes` list supports isolated devices and services that are not endpoints of a declared link. Each node needs `entity_id`; `name`, `role`, and `entity_type` are optional display details. Telemetry entities missing from the map are added to the dashboard graph as device nodes.

## Site files

For repeat use, store reviewed files in the repository or another local workspace:

```text
config/
├── profiles/
│   └── office-east.yaml
└── sites/
    └── office-east/
        └── topology.json
```

```bash
netcoop profile-init ./office-capture --name "Office East" \
  --output config/profiles/office-east.yaml
netcoop profile-validate config/profiles/office-east.yaml --data ./office-capture
netcoop triage ./office-capture --site office-east
```

Review generated profiles before using them. `profile-init` can suggest recognized metric mappings and list entity names, but it cannot infer every vendor's semantics, device roles, topology anchors, or whether a map is complete.
