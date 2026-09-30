# Workspace Topology

Status: normative
Owner: harness maintainers
Last verified: 2026-07-10

The supported developer layout is one Git repository whose root is both the harness root and the
only Salesforce DX project root:

```text
sf-harness-brain-core/       # Git repository, SFDX root, workspace folder: brain-core
├── sfdx-project.json
├── force-app/               # Salesforce metadata source
├── manifest/                # package.xml and related manifests
├── tests/e2e/               # promoted Salesforce end-to-end tests
├── .github/                 # Copilot instructions, agents, prompts, skills, hooks
├── .ai/                     # governed Knowledge and durable work state
├── work-items/              # durable Work Item artifacts, stable folders by ID
├── docs/solutions/          # optional three-file documentation, stable folders by solution
├── output/                  # ignored temporary drafts and reports
├── scripts/                 # harness runtime and validation
└── sf-harness.code-workspace
```

Open `sf-harness-brain-core/sf-harness.code-workspace`. It exposes one named folder:
`brain-core` maps to `.`. There is no second named Salesforce folder and no nested SFDX project.
The single root keeps metadata, governance, source control, review, and branch history together.
Opening the repository directory directly is also valid. Runtime configuration uses unqualified
`${workspaceFolder}` variables, which resolve in both direct-folder and single-root workspace-file
sessions.

The root owns `sfdx-project.json`, `force-app/`, `manifest/`, `tests/e2e/`, instructions, agents,
skills, Knowledge, Memory, cache, and generated drafts. Skills must resolve
`brain-core` as the one SFDX root and must reject a missing or ambiguous project rather than
searching a subfolder, parent directory, sibling directory, or other checkout.

Harness CI and metadata-dependent prompts
operate against the same checkout, so Salesforce metadata and the work item's design, tasks and
decisions remain reviewable in one pull request.

Requested technical documentation belongs at
`work-items/<id>-<slug>/technical-documentation.md`. Reuse the stable folder by ID; do not
rename it after an ADO title change. This optional document can describe existing state without
creating a design or other lifecycle files. It is eligible for Git tracking, but its location
does not establish review, deployment, or wiki publication. New references use the durable path.
`output/` remains ignored temporary storage for reports such as monthly handover, Feature Health,
and adhoc fix notes; historical drafts are not migrated automatically. Selected documentation
can be published to wiki through its separate workflow.

`/document-solution` writes a separate solution set in `docs/solutions/<solution-slug>/`:
`overview.md`, `flows.md`, and `components.md`. The Developer can edit only those three filenames
under a valid solution slug, without general `docs/` access. Reuse the same directory across
Stories; Work Item and design context are optional. These plain Markdown files describe available
implementation sources, including work on a branch that is not deployed. They do not replace
delivery documentation, handover, or governed Knowledge. Wiki publication remains separate.
See the [document-solution skill](../.github/skills/document-solution/SKILL.md).

The guarded Salesforce MCP launcher starts from `brain-core` and refuses to start when root
`sfdx-project.json` is missing; it runs review (read-only) mode only. Before tool discovery it
checks CLI authorization, validates the configured host/org-id pins, and proves the live
org identity over REST. Production reads follow role limits; production CLI permits only verified
metadata retrieve. Developer writes on `dev`/`uat`/`stage` use direct
Salesforce CLI rather than a write MCP. Root identity does not grant root-wide file authority: role
permissions bound file edits to approved metadata/test subpaths such as `force-app/`,
`manifest/`, and `tests/e2e/`. Harness instructions, Knowledge, work items, configuration,
and other governance content remain outside the Salesforce write scope.

Root `manifest/package.xml` is a generic starter manifest. Before an org-facing operation it must
be narrowed to the components named by the approved `work-items/<id>-<slug>/design.md`; wildcard
members are not authorization.

Do not create a nested `.git` or `sfdx-project.json`, relocate metadata to another directory, or
duplicate `force-app/` under a wrapper folder. Salesforce source and manifests are tracked at the
repository root alongside the harness that governs their lifecycle.
