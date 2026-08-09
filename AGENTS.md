# Agent Compatibility Contract

Use `.github/copilot-instructions.md` as the canonical always-on safety and grounding kernel.
Work runs through this checked-in workspace and a checked-in custom agent; the depth is
content, not machinery — `docs/` explains the package world, `.ai/knowledge/` holds
per-artifact facts, `work-items/` carries design, tasks, and decisions. Treat `brain-core` (`.`) as the only named workspace folder and the only SFDX root;
never search a subfolder, parent, sibling, or second checkout for metadata. Salesforce writes
remain bounded to the authorized root subpaths. Load detailed Principles, contracts, Knowledge,
and skills only through the active role. Orient in the generated atlas `.ai/repo-map.md` first.
Built-in/default Agent mode and arbitrary terminal workflows are not supported for external
systems or repository-state changes.

Supported host: **VS Code**. The per-agent role guard is wired through agent frontmatter, which
only VS Code reads; elsewhere it is silently absent even though `--agent` still loads an agent.
