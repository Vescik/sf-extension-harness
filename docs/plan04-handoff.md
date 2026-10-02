# Plan 04 — Wiki publication handoff

Date: 2026-10-02. Base: `main` at `1a579ef` (Plans 03, 03a, and 03b included).
Status: **LOCAL IMPLEMENTATION COMPLETE — local checks PASS** on `codex/plan04-wiki`.
GitHub CI, VS Code/ADO acceptance, remote publication, and migration are not verified.

## Delivered behavior

The Developer's `/publish-wiki` command publishes the three existing solution files or a delivery
document. The solution parent contains the overview; its children are Flows and Components.
The skill preserves stable addresses and manual content, maintains domain navigation, separates
deployed solution scope from branch implementation, and reports partial results by page and link.
Delivery documentation keeps its existing format and Story relation. Solution pages do not gain
automatic competing Story relations. See [usage and migration](wiki-publication.md).

The role and global safety hooks permit only the two narrow publication operations. Other ADO
mutations are denied; existing read roles and Salesforce/Knowledge authority remain unchanged.
Markdown content is data: source URLs and quoted commands do not become execution targets.
The actual project/wiki/path selectors remain validated. Chat authorization, deployed scope,
content reconciliation, page structure, and navigation remain the skill's responsibilities.

## Connector finding and bounded repair

The installed `@azure-devops/mcp` 2.8.1 callback first tries an unconditional create, then can
fetch the newest ETag and update using already prepared content. That does not bind an update
to the author's original read. Its relation callback also adds links without checking duplicates.

The existing launcher now preloads a selective module adapter. The same vendor server,
authentication, lifecycle, and stdio transport remain in use. No installed vendor file, second
server, page registry, durable cache, background synchronizer, or credential source is added.
The loader replaces only the Wiki registration module and the single artifact-link callback
inside Work Item registration. Its canonical paths cover symlinked dependency directories.

- Page reads return complete raw content and an opaque ETag from one response. Search extracts
  `page.content` before its existing sanitization/cache procedure, so handover keeps its contract.
- Updates compare the read ETag and perform one conditional PUT. Creation cannot fall through
  into an update. Conflicts and uncertain outcomes require another read, never an automatic
  stale overwrite. An identical page is a no-op.
- Scope, wiki project ownership, branch, full response, and canonical browser URL are checked.
  Scope is rechecked before mutation. HTTP page requests refuse redirects and have a timeout.
- Story linking verifies the live page, reads current relations, recognizes equivalent Wiki
  artifact/hyperlink identities, and adds only the missing Wiki Page relation with an internal
  revision test. It rereads the result; an uncertain write is not reported as success.

The API provides the same-response ETag on [page reads](https://learn.microsoft.com/en-us/rest/api/azure/devops/wiki/pages/get-page?view=azure-devops-rest-7.1)
and requires If-Match for [page edits](https://learn.microsoft.com/en-us/rest/api/azure/devops/wiki/pages/create-or-update?view=azure-devops-rest-7.1).
These fields stay in tool transport, outside user-facing revision reporting and source documents.

The new ADO policy module is included in both the native extension package and the portable
Salesforce pilot. Existing fail-closed imports remain in place; missing dependencies never relax
permissions. The first full run found the pilot copy omission, which was corrected in its source
list without changing the Salesforce assertions.

## Local verification

- Full Python suite: **1,284 tests, PASS, one existing skip**.
- Wiki page/link connector: **29 Node tests PASS**, including pinned vendor registration,
  symlinked dependency loading, concurrent writers, full content, unknown outcomes, and link deduplication.
- Static harness validator: **PASS**; generated repository map checked without drift.
- Deterministic safety evaluations: **82 PASS**. Native extension tests: **32 PASS**.
- Native build and VSIX packaging: **PASS**. All nine runtime files in the extracted VSIX match
  source and manifest; runtime verification and an isolated ADO-policy import pass.
- Python compilation, JavaScript lint, embedded-project Prettier check, and diff whitespace: **PASS**.
- Knowledge entry/Feature checks and index build: **PASS**; these do not certify Knowledge content.
- Production dependency audit at the required high-severity threshold: **PASS**; four moderate
  dependency advisories remain in the unchanged lockfile. No automatic dependency update was made.

The repeated full suite passed after the pilot-source fix. Its independent Salesforce assertions
were retained. The missing/broken Git-policy fixture now includes the unrelated ADO dependency,
so it still proves that a Git-policy import failure is the reason for denial.

An independent offline skill exercise covered missing deployment evidence, a manual edit plus
overlapping conflict, an existing same-page Story link, and partial publication after timeout.
It preserved the required scope and recovery behavior. This exercise is not host acceptance.

## Remaining acceptance

The implementation has not been pushed or published. No remote Wiki page, Story, or Salesforce
org was changed. No real ADO credentials or copied user configuration were used in tests.

Before a live pilot, install this complete checkout and its rebuilt native package in the target
VS Code Local host. Restart `ado-readonly` so the reviewed preload is active. Use an explicitly
selected wiki and disposable publication scope in the configured project. Verify:

1. New solution: parent plus two children, valid navigation, deployed-scope basis, and no Story relation.
2. Same solution updated: stable URLs, manual passages retained, duplicate request produces no writes.
3. Concurrent edit, absent page, denied access, and partial failure: honest page/link outcomes and bounded recovery.
4. Delivery document: published content and a single existing-compatible Story Wiki relation; handover still selects it.
5. Designer, Reviewer, search, and other roles cannot obtain publication rights; wrong project is refused.

Delivery linking requires one published branch in live Wiki metadata. An unavailable or ambiguous
branch is reported as incomplete. A Wiki artifact relation cannot select another branch; publish
delivery content to the verified published branch. Full migration requires a separate inventory
of the requested area and preservation of its historical URLs and relations.

Local tests and package verification do not prove native dialogs, live authentication/permissions,
remote service concurrency behavior, production deployment, or successful migration.
