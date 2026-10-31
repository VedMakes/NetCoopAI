# Network profiles

A profile maps a network's names and policy into NetCoop's current canonical observations. It does not add a collector or invent meaning for unknown fields. Keep one profile per deployment and commit it alongside its evaluation cases.

## Validate and run

```bash
netcoop profile-init path/to/sample-data --name "Branch office" --output config/profiles/branch-office.yaml
netcoop profile-validate config/profiles/campus.yaml --data fixtures/scenarios/dns_failure
netcoop diagnose path/to/telemetry --profile config/profiles/campus.yaml --format json
```

`profile-init` drafts mappings for source metric names NetCoop recognizes and lists observed entities. It deliberately leaves entity aliases, DNS/DHCP roles, topology anchors, and topology completeness for operator review. `profile-validate` checks the profile contract and, when given data, reports normalized observation count, whether configured topology anchors and DNS/DHCP roles appeared, and input warnings. Reports retain the profile ID and version.

For unfamiliar flat JSON/JSONL/CSV records, tell `profile-init` which source keys carry the standard fields. These repeatable options are preserved in the draft and let it inspect names and units before diagnosis:

```bash
netcoop profile-init vendor.jsonl --name "Vendor lab" --output vendor-profile.yaml \
  --source-field entity_id=node --source-field timestamp=observed_at \
  --source-field metric=measurement --source-field value=reading --source-field unit=units
```

## Profile fields

- `entity_aliases`: source entity name to stable canonical ID.
- `source_fields`: source key names for flat telemetry records and common topology fields. Common aliases such as `device_id`, `event_time`, `metric_name`, and `msg` are recognized by default; configure these when a source uses other names.
- `metric_mappings`: source metric name to a supported canonical metric and optional source unit. Known conversions are applied before diagnosis; incompatible units are quarantined. `counter_semantics` can mark count metrics as `interval_count` (the default behavior) or `cumulative_counter`; cumulative samples are differenced per entity and metric, the first sample is retained as a baseline only, and resets or duplicate timestamps skip the affected interval with a warning.
- `entity_roles`: canonical IDs and semantic roles such as `dns_resolver`, `dhcp_server`, `core`, and `edge`. Service diagnosis uses roles, not a required naming convention.
- `topology_anchors`: network-specific path roots used for common-upstream and impact analysis.
- `relationship_aliases`: source link/dependency type to a normalized relationship.
- `logical_relationships`: relationships that express dependencies rather than physical paths.
- `topology_completeness`: `complete`, `partial`, or `unknown`. Only a profile that declares a complete topology allows absence of a path to count as evidence of a partition.
- `rule_overrides`: typed threshold overrides for known rule keys. Unknown keys and invalid ranges fail validation.

Metric mappings currently target NetCoop's supported canonical metric set. A source metric outside that set remains a data-quality warning/quarantined input; adding an entirely new diagnosable signal still requires a canonical metric definition and analyzer support.

Profiles map flat records and known topology structures. Deeply nested collector payloads, vendor-specific semantics, and streaming device protocols need a small explicit adapter that converts into the flat input contract; profiles intentionally do not guess arbitrary nested meanings.

Counter differencing assumes samples for one entity and metric belong to the same counter stream. If a device reboots or changes interface identity, use a stable entity alias per interface/counter stream or expect a reset warning and a skipped interval.

## Examples and boundary

`config/profiles/campus.yaml` documents the sample network. `config/profiles/branch-office-example.yaml` illustrates different device names, roles, source metric names, units, anchors, and thresholds. The branch example is validated against a transformed synthetic case in the tests; it is not a production vendor adapter.

OpenConfig models use YANG and aim to provide consistent vendor-neutral models for common operational needs, while not covering every feature. IETF YANG defines structured network configuration/state and operations; gNMI exposes path-based telemetry subscriptions. These are appropriate future adapter targets, but this release accepts local JSON/JSONL/CSV inputs and does not connect to devices or parse arbitrary YANG models. [OpenConfig models](https://openconfig.net/projects/models/), [IETF RFC 7950](https://www.rfc-editor.org/info/rfc7950/), [gNMI subscription contract](https://github.com/openconfig/gnmi/blob/master/proto/gnmi/gnmi.proto).
