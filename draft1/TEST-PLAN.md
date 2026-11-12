# Test and acceptance plan

## P0/P1 collaboration and persistence
| ID | Test | Pass condition |
|---|---|---|
| T-001 | Two browsers same board | Drawing appears in both |
| T-002 | Concurrent shape edits | No unexplained loss or corruption |
| T-003 | Concurrent deletion/update | Defined conflict handling |
| T-004 | Disconnect and reconnect | Correct resynchronization |
| T-005 | Both clients close and reopen | Durable scene restored |
| T-006 | Restart API/collab services | Acknowledged edits recover |
| T-007 | Embedded image/file | File survives restart and export |
| T-008 | Board authorization | Unauthorized REST/WS denied |
| T-009 | JSON export/import | Scene and assets round-trip |
| T-010 | Offline runtime | No required Internet requests |
| T-011 | Multi-tab and stale revision | No stale overwrite |
| T-012 | Backup/restore | Board and asset integrity retained |

## P2 network modeling
- All icon categories available and labeled.
- Link types persist and render differently.
- Interface endpoint names round-trip.
- Duplicate/copy semantics do not invent a second real device.
- Removing a drawing object leaves canonical inventory unchanged.
- Planned and observed records remain separate.

## P3 local topology
- Import sample CSV/JSON fixtures; reject broken foreign keys.
- Reimport unchanged data with no duplicate objects.
- Search by name/site/type.
- One-hop expansion deduplicates cycles and enforces limits.
- Import refresh preserves hand-positioned nodes.
- Conflicting source assertions remain visible and traceable.

## P4 integration adapters
- Paginated reads, API failures, timeouts, partial data.
- Source ID reconciliation and deleted/stale observations.
- No write-capable API calls.
- Adapter contract tests against fixtures/mocks.

## Preliminary performance targets
- 2–10 collaborators per board.
- 50 concurrent users across boards.
- 1,000 elements per board.
- Catalog fixture representing 4,000 devices and 100,000 interfaces for search and bounded expansion tests.
These are test targets, not proven guarantees.

## Release evidence
Record environment, pinned versions, commands, test output, open defects, backup/restore evidence and acceptance signoff.
