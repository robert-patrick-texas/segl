# Canonical data model (draft)

## Primary entities
| Entity | Key fields | Purpose |
|---|---|---|
| `workspace` | id, name, created_at | Collection of boards |
| `board` | id, workspace_id, title, created_at, updated_at | Durable board |
| `board_revision` | id, board_id, revision, scene_json, asset_manifest, created_at | Restore/history |
| `board_member` | board_id, principal_id, role | Basic access control |
| `asset` | id, content_hash, path, media_type, size | Images/files |
| `network_object` | id, kind, name, lifecycle, metadata_json | Device/host/cloud/etc. |
| `interface` | id, object_id, name, metadata_json | Named endpoint |
| `network_link` | id, kind, endpoint_a, endpoint_b, lifecycle, metadata_json | Typed relationship |
| `data_source` | id, kind, name, config_ref, priority | Import/adapter source |
| `source_binding` | id, source_id, external_id, canonical_id, record_kind | Stable mapping |
| `observation` | id, source_id, canonical_id, observed_at, payload_json | Source evidence |
| `board_binding` | board_id, element_id, canonical_id, record_kind | Visual-to-domain map |
| `scenario` | id, board_id, name, baseline_revision | Planned change scope |
| `import_run` | id, source_id, started_at, status, counts, errors | Import audit |

## Enumerations
`network_object.kind`: router, switch, firewall, wireless_ap, server, workstation, printer, voip_phone, mobile, host, cloud, transport, unknown.

`network_link.kind`: cable, circuit, relationship, neighbor, connector.

`lifecycle`: observed, planned, retired_proposed. Do not infer production removal from `retired_proposed`.

## Modeling rules
- All primary keys are UUIDs generated internally.
- External IDs are scoped by source; hostname is not a unique identity.
- Interface name is unique only within a device and observation context.
- Endpoint may reference an interface or a device; preserve the distinction.
- A `neighbor` is not automatically a physical cable.
- Provider transport circuits may terminate on transport entities and must not imply direct branch-to-branch cables.
- Provenance includes source and timestamps; freshness is displayed.
- Imported observed records are immutable from board editing; proposed records are editable in a scenario.
- Visual element bindings are optional and can be many-to-one.
- Soft-delete or tombstone imported records after reconciliation; never erase historical snapshots silently.

## Minimal CSV contracts
`devices.csv`: `source_id,external_id,name,kind,site,management_ip,model`
`interfaces.csv`: `source_id,device_external_id,interface_name,description`
`links.csv`: `source_id,external_id,kind,a_device_external_id,a_interface,b_device_external_id,b_interface,observed_at`

## Minimal JSON example
```json
{
  "schema_version": "1.0",
  "source_id": "sample-inventory",
  "devices": [
    {"external_id":"dev-1","name":"core-01","kind":"router","site":"HQ"},
    {"external_id":"dev-2","name":"dist-01","kind":"switch","site":"HQ"}
  ],
  "interfaces": [
    {"device_external_id":"dev-1","name":"Gi0/0"},
    {"device_external_id":"dev-2","name":"Gi1/0/1"}
  ],
  "links": [
    {"external_id":"link-1","kind":"neighbor",
     "a":{"device_external_id":"dev-1","interface":"Gi0/0"},
     "b":{"device_external_id":"dev-2","interface":"Gi1/0/1"}}
  ]
}
```

## Import validation
Reject missing IDs, unknown kinds, broken endpoint references and duplicate conflicting IDs; report row/path and reason. Normalize only documented fields. Repeat imports must be idempotent.
