# Standalone Salesforce org-change logs

Use this directory only when a qualifying Salesforce org mutation has no applicable Work Item or
prepared Feature. The Developer creates one lazy, append-only file named
`<yyyy-mm-dd>-<short-safe-slug>.md` after the first command result.

The canonical trigger, placement precedence, required content, redaction, asynchronous update,
and verification procedure is `.github/skills/development/SKILL.md`. Do not copy Work Item or
Feature entries here and do not use this directory as a second ledger.

These files are agent-authored operational reports. They are not deploy consent, Knowledge,
independent evidence, release approval, QA execution results, or proof of current org state.
Never store credentials, authentication material, raw CLI JSON, record values, selectors, SOQL
literals, record IDs, usernames, inline Apex, business data, or raw input-file content.
