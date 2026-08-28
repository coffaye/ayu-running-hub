# Migration record

- Strategy: clean-history migration (the Hub starts with its own repository
  history).
- Source project: `coffaye/ayu-running-reports`.
- Source engine commit: `8cac5b96afd099db64b0981706f686692273db18`.
- Migrated scope: `engine/` implementation, schemas, sanitized fixtures,
  engine documentation and tests.
- Excluded scope: Codex plugin manifest/wrapper, Skill packaging, MCP config,
  local `.env` files, report/output directories and browser automation.

The source commit is recorded for traceability only. It is not a runtime path
or package dependency. Future changes should be made in this repository first
when they affect the Hub contract.

