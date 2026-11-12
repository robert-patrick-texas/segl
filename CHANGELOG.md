# Changelog

Summarized history of changes to source and documents. Newest release first. The release script turns `Unreleased` into the next release note. Keep the one-to-three sentence summary, then only the topic headings that have bullets: New, Changed, Fixed, Additional Notes.

## Unreleased

The project is specified, licensed, and public on GitHub, and application code has not started. This entry records that baseline for the first release notes.

### New

- Apache License 2.0 and the nine-slot MVP specification.
- One version manifest (`versions.toml`), a release script, this changelog, and `journal/` for the project narrative.
- The public repository <https://github.com/robert-patrick-texas/segl>, with GitHub private vulnerability reporting.
- nginx files in `deploy/nginx/`. They hold an upstream and WebSocket map, proxy settings (forwarded client address, a body limit above segl's own, timeouts, gzip), a `/board/` mount, and two example sites.
- `docs/DEVELOPMENT.md` lists the development host's tools, the checks, and the dev loop.

### Changed

- The Python pin is exactly 3.15.2 and follows the newest stable CPython uv offers. GitHub Releases are the publish destination. PyPI stays off until there is a demoable build.
- The contributor manual lives in `docs/`. `draft1/` and `draft2/` stay in the repository: frozen history, and the agent workbook.
- segl no longer has a `base_path` setting. It serves at its own root and works under any path nginx strips, such as `/board/` (D2-007).
- The web package uses npm, the newest Node LTS release, Vitest, Playwright Test, and Prettier (D2-023).
- Releases follow vakr's and Sunstone's policy. Every component moves to its newest release, a release that fails the tests is held with the reason, and currency is checked again at publish (D2-020). The release command is now task T01b.
- Development containers may run under rootful Docker (D2-015, S-017).
- The WebSocket carries title changes and newly placed images. Uploaded files are served at `/api/v1/assets/{hash}`. `trusted_proxies` decides whose `X-Forwarded-For` segl believes.
- The default display names no longer include Bush, Clinton, Obama, Trump, or Biden.
- The license header moved from the agent rules to `CONTRIBUTING.md`. The rule to comment out superseded code was removed.
