# Agent Compatibility Contract

Use `.github/copilot-instructions.md` as the always-on kernel. Work through this workspace and
a custom agent. `docs/` explains the package,
`.ai/knowledge/` holds artifact facts, and `work-items/` carries design, tasks, and decisions.
Treat `brain-core` (`.`) as the only named workspace folder and SFDX root; never search a parent,
sibling, nested project, or second checkout for metadata. The Developer may use direct
`sf`/`sfdx` for deployments, data mutations, and lifecycle work. Before every real deployment,
identify the target and scope in chat, state that changes will be deployed to the org, and obtain
confirmation for that exact invocation. Load contracts and skills through the active
role and orient in `.ai/repo-map.md`. Built-in/default Agent mode remains unsupported for external
systems or repository-state changes.

Supported host: **VS Code**. The per-agent role guard is wired through agent frontmatter, which
only VS Code reads; elsewhere it is silently absent even though `--agent` still loads an agent.
