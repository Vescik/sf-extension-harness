# Agent Compatibility Contract

Follow `.github/copilot-instructions.md`. `docs/` explains the package;
`.ai/knowledge/` holds facts; `work-items/` holds plans. `brain-core` (`.`) is the only SFDX root.
Load role contracts/skills and `.ai/repo-map.md`; never search another root for metadata.

Developer uses reviewed CLI on `dev`/`uat`/`stage`. Production CLI permits only verified metadata
retrieve; other reads use Salesforce MCP within role limits. Test Strategist cannot target prod.
Unknown targets/latest require the native Developer tool with arguments only; its dialogs own
one-use environment selection and exact deployment confirmation. Never launch private helpers or
supply approval/environment fields. See `docs/native-salesforce-operations.md`.
Before a real deploy, identify target/scope and warn that changes reach the org; confirm that exact
invocation. Native execution requires its modal confirmation.

Governed Salesforce/ADO and protected non-Git edits require **VS Code Local** custom-agent
frontmatter hooks, unavailable in default Agent mode. Git/gh work independently, with only
commit-message validation. Preserve unrelated work; publication, merge,
and destructive actions require explicit instructions.
