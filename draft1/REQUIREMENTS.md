# Product requirements and acceptance criteria

Priority codes: **M** = must for phase; **S** = should; **L** = later. IDs are stable for traceability.

| ID | Phase | Priority | Requirement | Acceptance |
|---|---|---|---|---|
| W-001 | P0 | M | Embedded Excalidraw | Editor works inside segl UI |
| W-002 | P0 | M | Real-time collaboration | Two users see edits and cursors |
| W-003 | P0 | M | Durable boards | Reopen after both users leave |
| W-004 | P0 | M | Restart recovery | Scene restored after service restart |
| W-005 | P0 | M | Board CRUD | Create/list/rename/duplicate/delete |
| W-006 | P0 | M | Import/export | Native scene JSON round-trip |
| W-007 | P0 | M | Runtime self-hosting | No mandatory external service |
| W-008 | P0 | M | Board access control | Unauthorized join/API denied |
| W-009 | P0 | S | History/restore | Recover earlier revision |
| W-010 | P0 | S | PNG/SVG export | Images render accurately |
| N-001 | P1 | M | Device palette | All specified device kinds present |
| N-002 | P1 | M | Typed connections | Cable/circuit/relationship/neighbor/connector |
| N-003 | P1 | M | Device object metadata | Stable UUID and display name |
| N-004 | P1 | M | Existing/planned distinction | Visible styles and persisted state |
| N-005 | P1 | M | Drawing/data separation | Deleting shape never deletes inventory |
| N-006 | P1 | S | Interface-aware endpoints | Named interfaces where available |
| I-001 | P2 | M | CSV device import | Valid rows stored, invalid rows reported |
| I-002 | P2 | M | JSON import | Schema validation and repeatable import |
| I-003 | P2 | M | PostgreSQL catalog | Device/interface/link search |
| I-004 | P2 | M | Place existing device | Search and add by name |
| I-005 | P2 | M | Neighbor expansion | One-hop preview and dedup |
| I-006 | P2 | M | Provenance | Source ID and timestamp visible |
| I-007 | P2 | M | Non-destructive refresh | Existing layout preserved |
| I-008 | P2 | S | Two-hop expansion | Limits and preview |
| A-001 | P3 | S | Nautobot adapter | Read-only canonical import |
| A-002 | P3 | S | NetBox adapter | Read-only canonical import |
| A-003 | P3 | S | Checkmk adapter | Read-only canonical import |
| A-004 | P3 | S | Source reconciliation | Conflicts surfaced, no silent override |
| E-001 | P4 | L | Enterprise SSO | OIDC/SAML and agency IdP integration |
| E-002 | P4 | L | Encryption at rest | Policy-approved key management |
| E-003 | P4 | L | Advanced audit/RBAC | Policy-aligned events and roles |

## Initial symbol types
Router; switch; firewall; Wi-Fi access point; server; workstation; printer; VoIP phone; mobile device; generic host; unknown device; transport/cloud. Future extension via versioned symbol manifest.

## User experience requirements
- Whiteboard starts in one click after entering a workspace.
- Network palette is optional and never obstructs normal Excalidraw tools.
- A device can be added manually without inventory connectivity.
- Typed links communicate their meaning visually and via metadata.
- Import and refresh errors are actionable and do not corrupt existing boards.
