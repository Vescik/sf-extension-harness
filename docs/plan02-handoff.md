# Plan 02: language and durable documentation

Date: 2026-09-28
Implementation: complete locally; local checks passed. Full host acceptance remains open.
Host pilot: deferred by the owner. The results below are the local verification snapshot;
hosted CI results belong to the publication PR's checks.
Base: `main` after PR #50, commit `4f318bd13e4988a2a3da0adaaec2c04912a8f7a7`.
Branch: `codex/plan02-writing-artifacts`. After local verification, the owner requested commit and merge.

## Behavior

- The kernel defines conversation-language replies and English/STE artifact prose.
  All eight roles reference one [writing standard](../.ai/contracts/writing-standard.md).
  Source quotations, literals, uncertainty, and task-specific language requests are preserved.
- QA uses the artifact default. New unapproved design decisions use `[unapproved]`.
  QA reads the optional technical document only when its task needs it.
- Requested Work Item documentation uses
  `work-items/<id>-<slug>/technical-documentation.md`. One matching ID reuses its folder.
  Duplicate folders stop writes. A verified item without a folder creates only its document.
  Updates retain unrelated human notes and do not inherit earlier acceptance.
- The nine-section document presents the design's verification strategy. It does not create
  requirements or suggest Test Cases. Local storage does not prove deployment or wiki publication.
  Handover retains its attached-wiki requirement and fixed missing-link fallback.
- Handover and Feature Health keep their temporary paths and existing section structure.
  Their headers distinguish document review state, scope, sources, checks, and gaps.

The [shared contract](../.ai/contracts/execution-contract.md),
[technical-documentation procedure](../.github/skills/generate-technical-documentation/SKILL.md),
[work-item guide](../work-items/README.md), consumer templates, and generated map describe the same behavior.
The pinned upstream version and full MIT license are in
[the provenance directory](../.ai/third-party/asd-ste100/README.md).

## Local verification

Environment: macOS arm64, Python 3.12.14, Node 24.11.1. Dependencies use the existing lockfiles.
The unchanged baseline passed static validation with 2764 assertions and 212 focused tests.

| Check | Result |
|---|---|
| Full Python unit suite | PASS: 1138 tests in 169.488 seconds; one existing filesystem case-sensitivity skip |
| Focused validator and hook suites | PASS: 221 tests, including nine new regressions |
| Handover and output-envelope suites after final consumer edits | PASS: 21 tests |
| Static harness validation | PASS: 2833 assertions on the final source and handoff |
| Generated map check | PASS |
| Deterministic safety evaluations | PASS: 67 |
| Native extension tests, build, and VSIX package | PASS: 32 tests; package built, not installed |
| Knowledge entry/Feature integrity and index build | PASS |
| Python compile, launcher syntax, lint, and project formatting | PASS |
| Production dependency audit at the CI high-severity threshold | PASS; two moderate findings remain |
| Diff whitespace, role frontmatter, document sections, and ignore rules | PASS |

The existing validator requires `.git` to be a directory, so it rejects a linked worktree's
`.git` file. Full validation uses an ordinary local clone with byte-identical tracked and new
source files. No validator rule was weakened. Python tests use synthetic fixtures; they do not
establish live Salesforce, ADO, Windows, or Copilot behavior.

The new checks verify shared-contract wiring for current and future roles and the documentation
path's trackability. Guard tests allow Developer documentation writes, deny Reviewer and QA
writes, and reject outside paths and symlink escapes. Existing QA design-write denial still passes.
No runtime guard, tool list, agent hook, schema, dependency, or external configuration changed.

## Acceptance still open

The owner deferred the VS Code pilot during implementation. The inspected Local window showed
`Models, sign in to use Copilot`; no Plan 02 model response was obtained. Installed versions were
VS Code 1.138.0 and bundled Copilot 0.66.0. GitHub sign-in alone is not proof of model access.

- L01-L05: conversation and artifact language, source-instruction isolation, meaning preservation,
  and automatic instruction loading need actual built-in and custom-role responses.
- A01-A06: stable-folder selection, duplicate rejection, no-design authoring, reviewed-document
  updates, incomplete evidence, and cross-document consistency need the agent workflow pilot.
  Local path, ignore, template, and guard checks cover only their structural parts.
- G01-G02: role boundaries and containment have local regression evidence. Live host enforcement
  and sanitization of generated documents still need the pilot.
- Windows host behavior remains unverified. Hosted CI was not run during local verification;
  consult the publication PR's checks. CI on Windows does not prove VS Code host behavior.

Resume with a fresh VS Code Local session after a model is available. Start with built-in chat,
Designer, Developer, Test Strategist, and Reviewer; then test the other four roles. Use synthetic
sources and a disposable workspace copy. Keep read-only roles read-only. Record actual responses,
files, role/model/version, and instruction loading. Do not deploy or publish to test writing style.

For cost comparison, use the same short reply, new Story document, and document update before and
after the patch. Keep the model and sources constant. Record elapsed time, calls, iterations, and
output length. Host token counts and latency are unavailable in this local verification.

Static size review: the kernel adds 91 words; the writing rules contain 305 words before Origin;
each role reference adds 13 words. These are word counts, not token measurements. Instructions add
no style-only external calls, translator, rewrite pass, or routine whole-folder read.

## Scope and rollback

Plan 03 revision/commit changes, ADO configuration, wiki migration, Test Cases, and Knowledge
redesign remain outside this patch. No external system was changed and no old `output/` draft
was migrated. To revert, remove only this patch's changes. Preserve any user documentation
created later under `work-items/` and its existing publication or review history.
