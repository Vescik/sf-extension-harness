# Plan 03: workflow implementation and acceptance

> Historical implementation record. The owner superseded its Git/gh restrictions on
> 2026-10-05: all roles can use all Git/gh commands, with only commit-message validation.
> Current instructions are in [Git Workflow](../.github/skills/git-workflow/SKILL.md).
> The ADO changes and historical verification below retain their original scope.

Status: local implementation verified on 2026-09-29; see the 2026-09-30 audit follow-up below.
Host, controlled ADO and PR acceptance remain open.
The owner approved the plan and explicitly requested implementation on 2026-09-29. Publication
and merge require their own explicit instruction; implementation does not authorize either.

## Behavior

- New ADO caches use schema v2 without transport revision metadata. Valid v1 caches remain
  readable with their original retrieval time. Content, source identity, projection scope,
  completeness, and staleness retain their meanings. Equivalent normalized source content and
  projection scope do not rewrite tracked documents just because a fetch time or legacy revision changed.
- A difference between current ADO content and design can be useful information. It does not
  mandate redesign or expand the assigned work. Required source reads, real missing evidence,
  duplicate identities, partial results, and explicit Feature membership remain significant.
- Designer, Developer, Test Strategist, and Workspace Maintainer prepare a delivery branch and
  commit a coherent permitted result through the shared
  [Git Workflow](../.github/skills/git-workflow/SKILL.md). Exact file staging and commits check the
  entire index and freshly hashed working-tree content using Git's clean conversion, including
  CRLF normalization. Git Agent retains its broader Git repertoire. Authors can resume a
  verified branch that exists only on `origin` through explicit tracking-branch creation.
- All eight roles have bounded GitHub CLI reads. The four author roles and Git Agent can perform
  explicitly requested publication and PR operations. The sole PR body transport path is the
  ignored `.cache/github/pr-body.md`. Merge requires a concrete PR and expected full head SHA.
  A publication request creates a Draft unless Ready is explicitly requested.
- Reviewer remains read-only. Knowledge authorship, approvals and revisions remain on their
  existing path. Production policy, the native operation tool, and persistent technical
  documentation from plans 01/01a/02 retain their boundaries.

## Enforcement boundaries

`git_workflow_policy.py` parses commands and inspects local Git state. Both hooks use it; missing
policy code or an inspection failure fails closed. It does not execute admitted commands, make
network requests, store consent, or infer semantic ownership from a path or `AB#` reference.
Quoted commit descriptions and PR titles are data; chaining, command substitution and unquoted
shell expansion remain forbidden. File paths, options and the actual executable remain subject
to the guard. Windows ambiguous escaped quotes are rejected. Existing PR body files must be
regular, without symlink or hardlink indirection.

The active agent verifies source identity, semantic scope, the user's operation authority, and
current remote PR state through the workflow. The hook cannot attest conversation authorization,
required reviews, or remote outcomes. Native terminal approval may still appear. No shared
terminal auto-approval setting is added. One active writer is required: there is no atomic
transaction spanning inspection, staging, commit, and post-command verification.
Local Git inspection has a three-second budget so a stalled preflight can return a valid denial
before the role hook timeout. On Windows, Git's index mode is authoritative because the POSIX
executable bit is unavailable; on POSIX it is compared independently of `core.filemode`.

The ADO schema validates shape and reserved metadata keys. Matching the item ID to its source,
the configured organization/project, projection scope and source completeness still belongs to
the agent workflow. This patch adds no ADO executor or automatic legacy-file migration.

## Local verification

Final verification used a disposable ordinary clone on macOS, Python 3.12.14, Node 24.11.1,
Git 2.54.0 and GitHub CLI 2.90.0. The unit suite uses real temporary Git repositories for
branch/index/worktree checks and invokes both hooks. These checks establish local policy
behavior, not Copilot host enforcement or semantic ADO behavior.

| Check | Result |
|---|---|
| Static harness validation | PASS, 2937 assertions |
| Full Python suite | PASS, 1204 tests in 167.720 seconds; one existing case-insensitive filesystem skip |
| Deterministic safety evaluations | PASS, 82 scenarios |
| Native operation tests | PASS, 32 tests |
| Native build/package and isolated packaged import | PASS; all seven runtime files match the final sources |
| Repo map, Python compilation, JavaScript parsing, diff check | PASS |
| Knowledge entry/Feature checks and search build | PASS; no Knowledge lifecycle changes |
| Salesforce formatting and JavaScript lint | PASS |
| Dependency audit at the CI high-severity threshold | PASS; three moderate findings remain in unchanged dependencies |

The native extension now packages and verifies the shared Git policy dependency with its
other runtime files. A regression test builds that package and imports the real Salesforce
session outside the repository with isolated Python. It requires an explicit success marker;
exit code zero alone is insufficient because a fail-closed hook can exit successfully with
a denial. The generated VSIX was also extracted and imported in isolation. It was not installed
into or accepted by a Copilot host during this implementation.

Reproduce in a disposable ordinary clone with Python dependencies installed:

```text
python scripts/validate_harness.py
python -m unittest discover -s tests -v
python scripts/run_evals.py
python scripts/render_repo_map.py render --check
python -m compileall -q scripts tests
npm run native:test
npm run native:build
npm run native:package
npm run prettier:verify
npm run lint
```

The static validator expects an ordinary `.git` directory. A linked worktree alone is not
equivalent evidence for that layout check. Do not weaken the check to obtain a passing result.

## Audit follow-up on 2026-09-30

The owner requested a compatibility repair for legacy Feature maps. The reader accepts an
explicit ID column in another position and numeric IDs with Markdown emphasis, inline code,
or numeric link labels. It preserves saved maps and the exact included/deferred selection.
Titles and link destinations are not identity sources; ambiguous identities and conflicting
membership remain denied. New maps keep the existing writing convention.

Local verification passed: 1207 Python tests (one existing filesystem skip), 2937 static
assertions, and 82 deterministic safety evaluations. The full suite includes isolated native
runtime import and new role-hook cases for legacy maps, ambiguous identities, and preservation
of HEAD, index and map bytes. All five cases from the original compatibility reproduction now
allow the intended member without changing the map. Syntax, repo-map and diff checks passed.
These results do not establish Copilot host or live ADO acceptance.

The owner then requested the Feature-ref and performance fixes and a push of the delivery
branch. Clean Feature resume now reads context and map from the exact target commit. Parallel
children and child PRs use membership at the resolved remote Feature base. New local intake
and dirty-change preservation retain their separate working-tree checks.

Git preflight now batches ignored-file, diff, index and fresh-hash inspection. Argument groups
are bounded for Windows and POSIX, and all groups share the existing three-second deadline.
Clean filters, line endings, staged deletions, file modes and index equality remain checked.

Final local verification passed: 1223 Python tests in 212.582 seconds (one existing
case-insensitive filesystem skip), 2943 static assertions, 82 deterministic safety evaluations,
and 32 native tests. Repo-map, Python compilation, formatting and diff checks passed. The built
VSIX has all seven runtime files matching the tested sources; manifest verification and an
isolated Python import reached their explicit success markers. Independent review found no
remaining actionable issue in these fixes. Four real-Git reproductions confirm target/base
membership and clean resume without using the current checkout's Feature map.

| Role-hook commit preflight | Before | After |
|---|---|---|
| 50 files | 261 Git processes; 2.621 seconds; allow | 15 Git processes; 0.173 seconds; allow |
| 100 files | 272 Git processes before the 3.004-second timeout; deny | 15 Git processes; 0.183 seconds; allow |

These are single-run measurements on the local macOS fixture, not Windows performance or host
acceptance. Regression tests cover multiple argument groups, clean filters and CRLF, partial
staging, same-size/mtime edits, index flags, recreated deletions, malformed/partial output,
argument limits and the shared deadline. The runtime, test and skill sources remained unchanged
after the full suite; only this result paragraph was finalized before repeating static validation.

The owner accepted the implicit GitHub CLI repository-selection limitation for the team's
single-repository configuration. Reads without an explicit repository selector can follow
GitHub CLI's configured default remote, which the current guard does not resolve. This
acceptance does not change the code or the explicit repository requirement for writes.

## Remaining acceptance

| Evidence | Status and required check |
|---|---|
| Controlled agent ADO behavior | Not verified. Run the ADO scenarios in `evals/agent-scenarios.yaml` with controlled responses; compare tracked bytes, ignored cache time, and source scope. Schema validation alone cannot prove semantic no-op. |
| VS Code Local on macOS | Not verified. The inspected Local host displayed `Models, sign in to use Copilot`; no Plan 03 invocation reached its hooks. Start a fresh trusted session after authentication. |
| VS Code Local on Windows | Not verified. Test on the team's actual host and shell; platform-specific parser tests are not host evidence. |
| PR create/edit/ready/merge | Not verified live. Use a designated test repository and branches with explicit test authority. Inspect remote state after each command and after timeouts; queued is not merged. |
| Release and remote CI acceptance | Not verified. The owner requested a delivery-branch push; that publication does not establish CI success, a release, or host acceptance. |

For each host record the source commit, OS, VS Code/Copilot/Git/gh/Python versions, trusted-workspace
and hooks settings, role/prompt effective tools, and actual terminal tool payload. Exercise both
the global and per-role hook, including alternate terminal names. Use synthetic local repositories
for bootstrap, mixed index, staged/unstaged edits, renames, deletion and file-mode cases. Preserve
all existing user work.

Run the manual scenarios for equivalent/changed ADO content; v1/v2 and partial/stale evidence;
prepared Feature membership and omitted `include`; local author milestones; explicit publication
versus merge; read-only roles; PR body symlinks; literal descriptions versus real shell execution;
and unchanged native Salesforce policy. A host failure or unavailable connection stays visible
as an acceptance gap. Do not replace it with a static-check result.
