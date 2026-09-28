# Production read-only isolated release handoff

Status: approved for publication as plan 01 only; destination host/live acceptance remains with
the owner. This document does not claim that a push, merge or destination acceptance has occurred.

## Release scope

The release starts from remote-main baseline `0af14c1` and ports only the production-policy delta
`e329fa5^..e329fa5`, with manual conflict resolution for that older baseline. It does not import the
intervening Knowledge redesign, ADO changes, other September plans, or plan 01a implementation.
The existing Knowledge entries, tools, approval ledgers and org-sampling containment are retained.

Included behavior:

- Canonical configured environments `dev`, `uat`, `stage`, `prod`, arbitrary valid aliases,
  multiple orgs per environment, and explicit legacy migration.
- Shared CLI target/identity policy before deploy confirmation; production allows only verified
  metadata retrieve. Other production reads use the existing read-only Salesforce MCP within
  role, live-identity, denylist and data limits.
- Lifecycle parent/Dev Hub target handling, onboarding environment selection and alias updates,
  nonprod preview parsing already present in the source correction, duplicate-alias diagnostics,
  and production-policy instructions adapted without changing the Knowledge architecture.
- Credential-free process/host pilot assets and local regression coverage.

The lockfile also updates the existing transitive `fast-uri` dependency from 3.1.5 to 3.1.7 so the
baseline dependency tree can satisfy the existing high-severity audit gate. This is one lockfile
package update, not a new runtime feature or broader dependency migration.

## Accepted decisions and remaining work

| Item | Release treatment |
|---|---|
| Default target / `SF_SFDX_INTEROPERABILITY=false` discrepancy | Owner checks their destination; no fix or completed validation is claimed here. Prefer explicit targets. |
| Test Strategist production target prohibition | Retained in the agent and both QA workflows. The owner accepts instruction-only enforcement; no additional runtime role/target binding task is required by this release. |
| Unknown CLI org question / P1-02 | Deferred to plan 01a. Existing unresolved-target denial remains; no fabricated user answer or persistent classification/approval store. |
| Remaining nonprod/latest workflow compatibility | Deferred to plan 01a. Supported behavior and exact real-deploy confirmation remain; no broad pass-through or silent relaxation. |
| VS Code hooks, approval binding, OS behavior and real retrieve/MCP | Destination acceptance belongs to the owner and remains NOT VERIFIED here. |
| Knowledge observation persistence | Existing containment and approval contract preserved; live production MCP read permission does not expand persistence lanes. |

Read [the channel contract and migration](production-read-only.md) before installation. Use
[the portable pilot](production-policy-pilot.md) for denial tests without real credentials. Confirm
actual installed CLI retrieve semantics and bounded read access separately. Test Strategist's
instruction-level restriction is not a claim that runtime tool calls attest their caller and org.

## Evidence provenance

The previously reviewed source commit `e329fa5` had 722 unit tests, 2,260 static checks and
64 deterministic evals passing. Those are historical source-branch results; they do not prove
this backport on `0af14c1`. Fresh isolated-snapshot checks must be recorded separately by the
release operator. Neither set proves destination host enforcement, live Salesforce access or
asynchronous retrieve completion. No forbidden production operation is needed for validation.

## Fresh isolated-snapshot validation

Validated on 2026-09-28 in a clean Git clone based on `0af14c1`, with only this plan 01
backport and the compatibility adjustments described above:

- Unit suite: 1,064 tests run, 1,063 passed, one case-fold collision test skipped because the
  local filesystem is case-insensitive. No failures or errors.
- Static harness validator: 2,580 assertions passed.
- Deterministic safety evaluations: 60 passed.
- Existing Knowledge entry and feature integrity checks passed; search index build passed.
- Python compilation, Node syntax checks, ESLint, Prettier, Git whitespace checks and ignored
  local-state canaries passed.
- `npm ci --ignore-scripts` passed. `npm audit --omit=dev --audit-level=high` passed, with two
  existing moderate findings (`hono` and `qs`) below the repository's blocking threshold.

These are local results for the isolated backport. GitHub CI results belong to its PR.
Destination-host hooks and live Salesforce retrieve/MCP acceptance remain owner checks.
