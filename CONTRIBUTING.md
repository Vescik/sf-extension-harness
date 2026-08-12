# Contributing

This repository is a safety-sensitive AI development harness. Keep changes small, reviewable, and
traceable to a work item or recorded decision.

## Workflow

1. Branch from the current default branch; do not work directly on `main`.
2. Read `AGENTS.md`, the root Copilot instructions, and the applicable Tier 1–3 rule files.
3. Preserve role separation: design, implementation, testing, investigation, and independent
   guardrail review are distinct responsibilities.
4. Never replace a human-owned placeholder with an invented value.
5. Run the validation commands in the pull-request template.
6. Open a draft pull request early and include unresolved evidence gaps explicitly.

## Change rules

- Keep production aliases, production URLs, credentials, tokens, customer data, and local browser
  profiles out of the repository.
- Do not commit `config/harness.local.json`, `.cache/**`, or `output/**` artifacts.
- Salesforce source under `force-app/` is versioned. After a retrieve, inspect `git status`/
  `git diff` and stage only the exact intended metadata paths; never use a broad `git add` in a
  mixed workspace.
- Any new public slash command needs an owner, stable name, pinned agent, input contract, and
  deterministic failure behavior.
- Any new custom agent needs a bounded role, current tool IDs, correction handoffs, and safety tests.
- Any new external integration needs point-of-use validation (fail-closed at its own startup or
  per call), an allowlist, a sanitized cache contract, and a negative test.
- Changes to stable `SAFE-*`, `MP-*`, `ORG-*`, or `SF-*` rules require an explicit reviewer and a
  decision-log entry.

CI proves repository structure and deterministic controls. It does not replace live VS Code
Customization Diagnostics or non-production integration smoke tests.

## CI lanes

Pull-request CI is diff-aware (`scripts/classify_ci_changes.py`). Only two path classes skip
the full harness: `force-app/**` runs the bounded Salesforce lane (formatting, lint, and the
advisory Integration Field Impact Check against `config/integration-fields.yml`), and
`work-items/**` is delivery content that runs neither heavy lane. Every other path — including
new, unlisted ones — runs the full harness. The always-created `PR CI / Gate` check aggregates
the required lanes; a lane may be skipped only when the classifier declared it unnecessary.

The integration field registry maps `ObjectApiName.FieldApiName` identities to the integrations
that consume them; the integration owner named in each entry maintains it (see the header of
`config/integration-fields.yml`). A registered-field match is advisory and never blocks a merge;
a malformed registry or a crashed checker fails the Salesforce lane.
