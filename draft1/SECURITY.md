# Security staging — segl

## Delivery posture
Rapid usability is the priority, but the initial deployment must not expose internal diagrams or imported management information without basic protection. Advanced federal controls can be added later without changing the core data model.

## Minimum safeguards for P0–P2
- Bind services to internal interfaces or localhost behind a reverse proxy.
- HTTPS/WSS for shared deployment; trusted enterprise certificate.
- Simple local authentication or trusted identity gateway; board-scoped authorization enforced by REST and WebSocket services.
- No anonymous public share links by default.
- CSRF/CORS controls, input validation, secure cookies/session expiry, upload size/type checks.
- Secrets via protected environment/secret files, never committed or embedded in scenes.
- Runtime has no required external SaaS endpoints; self-host fonts/assets.
- Backup and restore for PostgreSQL, scene snapshots and assets.
- Dependency pinning, vulnerability scanning, license review and safe default configuration.
- CSV/JSON imports treated as untrusted input; prevent spreadsheet formula injection on export and path traversal on upload.
- No write-capable network-device credentials or automated configuration changes.

## Deferred enterprise capabilities (P4)
- SAML/OIDC, PIV/CAC through enterprise identity services.
- Granular RBAC and lifecycle management.
- Encryption at rest, key rotation, approved cryptographic modules.
- Comprehensive audit retention and SIEM integration.
- Compliance control mapping, hardened images, SBOM/signatures, HA/DR and formal authorization package.

## Threats to address during design
Unauthorized room join; guessed board identifiers; stale session overwrite; cross-board data leakage; malicious file import; stored XSS in metadata; exposed inventory secrets; unsafe outbound requests by integrations; denial of service from huge scenes or topology expansion.

## Federal deployment note
A prototype or pilot is not automatically authorized for production federal data. Agency system owners must determine the approved environment, data sensitivity and required controls before operational use.
