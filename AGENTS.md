# Agent Compatibility Contract

Use `.github/copilot-instructions.md` as the kernel through a custom agent.
`docs/` explains the package; `.ai/knowledge/` holds facts; `work-items/` holds plans.
`brain-core` (`.`) is the only workspace and SFDX root; never search outside it for metadata.
The Developer may use direct `sf`/`sfdx` on `dev`/`uat`/`stage`.
Production CLI permits only verified metadata retrieve; other production reads use read-only
Salesforce MCP within role limits. Test Strategist cannot target production, including MCP.
Unknown CLI targets remain denied. See `docs/production-read-only.md`.
Before every permitted real deployment, identify target and scope in chat, state that changes
will reach the org, and obtain confirmation for that exact invocation.
Load contracts and skills through the active role; orient in `.ai/repo-map.md`.
Built-in/default Agent mode is unsupported for external systems or repository-state changes.

Supported host: **VS Code**. Per-agent guards use frontmatter hooks, silently absent elsewhere
even when `--agent` loads an agent.
