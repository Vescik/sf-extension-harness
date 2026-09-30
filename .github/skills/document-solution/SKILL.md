---
name: document-solution
description: Create or update three plain Markdown files that explain one implemented Salesforce solution, its scenarios, components, and rationale.
user-invocable: false
---

# Document a solution

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and its
plain Markdown exception for this workflow. Use the existing Developer role. Write new prose
in English/STE under the [writing standard](../../../.ai/contracts/writing-standard.md).

## Inputs and boundaries

Require a recognizable solution topic and scope. Use named components, directories, existing
documentation, and task context. Ask only when ambiguity materially affects scope or destination.
Optional inputs are a positive integer `itemId` and
`documentationPath=docs/solutions/<solution-slug>/`. These are prompt inputs, not a new CLI.
Resolve the repository root (`brain-core`) as the only SFDX root. Never search another root for metadata.

Describe implementation found in the available sources. A branch can contain implemented work
that is not deployed. State that distinction when material. Merge or Story completion does not
prove production deployment. Keep future proposals in the existing design or Story.
Route a design-only request to `/solution-design`; do not add a design mode or permanent
`Current`/`Proposed` sections to this workflow.

A Work Item is an optional source and link. If supplied, use the existing scoped ADO reads and
source rules. Read relevant local design and decisions when present. Preserve source identity,
partial results, sanitized quotations, and API identifiers. Do not collect ADO revision numbers.
A missing Work Item or design does not block documentation of existing behavior. Do not create
a substitute design, fictional ID, intake record, or lifecycle files.

This workflow adds no required Knowledge lookup, authoring, or bootstrap. If the task already
uses Knowledge, keep its existing read and reference-validation rules. Missing Knowledge does
not block documentation from available sources. Org access is optional when those sources suffice.
Any needed org read remains subject to the Developer's existing environment and role limits.

Run only when requested. Do not make documentation a Story completion gate or require other
roles to load the set. Do not invoke `/document-metadata-change`, handover, Knowledge authoring,
wiki publication, or ADO link updates. Existing delivery documentation remains in place.

## Find the stable destination

One solution owns one directory with exactly these output files:

```text
docs/solutions/<solution-slug>/
├── overview.md
├── flows.md
└── components.md
```

1. Read the supplied directory first. Without one, search only `docs/solutions/` for the topic
   and its main components. Reuse one clear match. Resolve multiple plausible matches with
   the user before writing. If none exists, choose a stable lowercase slug with hyphenated words.
2. Validate `documentationPath` before writing. It must name one direct solution directory
   under `docs/solutions/`, with a slug matching `[a-z0-9]+(?:-[a-z0-9]+)*`.
   Resolve paths against the repository root. Reject traversal, symlink components (including
   in-repository redirection), hard-linked destination files, and paths outside the three
   permitted filenames. An input path grants no authority.
3. Use documentation elsewhere only as a source. Surface a likely duplicate before creating a
   competing set. Moving, deleting, or migrating existing documents requires its own scope.
4. For an update, read all three files. Preserve human notes and useful sources. Change only
   passages affected by the request, then review consistency across the set. A missing file can
   be completed in that same directory; do not replace the existing files wholesale.

Keep the path after title changes and later Stories. A bug fix updates relevant passages;
a refactor with no effect on the description needs no date-only edit. If a requested change
affects several solutions, update their existing sets within that scope. Create a new set only
for a distinct solution, never for each Story or release. Do not create copies in `output/`,
Work Item folders, Knowledge, or separate business-domain folders. Wiki domains can link to
one solution set through the separate publication workflow.

## Three-file content

Use these sections where they help the reader. Scale detail to the solution; omit empty
technology sections and group simple helpers. Put useful source links beside the explanation.
Use relative links between repository files, including links among the three output files.
Keep `overview.md` as the entry point and link it to `flows.md` and `components.md`.

| File | Responsibility and suggested sections |
|---|---|
| `overview.md` | Title; Purpose and scope; Architecture at a glance; Data, configuration and access; Material change impact when relevant; Limitations; Related work and documentation. Include useful Work Item and source links, without a full change log. |
| `flows.md` | Scenario index; for each scenario: Trigger and preconditions, Execution, Outcome and failures, Verification. Explain how components work together and link to their descriptions. |
| `components.md` | Component catalog, then descriptions grouped by actual technology or responsibility. Cover Role, Entry points, Behavior, Contract and effects, Dependencies, Failures, Rationale, and Sources where material. |

The catalog gives each component's name, type, responsibility, and description or source link.
It can include unchanged dependencies and is not a deployment manifest. For material components,
explain rules, inputs, outputs, effects, errors, and dependencies:

- Apex: material transaction boundaries and access rules.
- LWC: states and communication.
- Flow: conditions, activation, and fault paths.
- Other technologies: the behavior supported by their actual sources.

Explain an error's outcome in its flow and its mechanism in the component description.
Link the two instead of repeating full explanations. Separate documented rationale, the author's
technical assessment, and unknown intent. Never invent motivations or previously considered alternatives.

Distinguish tests found, checks actually run, and behavior confirmed in an org. Link available
evidence and state material limits near the relevant description. This does not create a QA plan
or replace delivery-documentation verification. A before/after comparison needs a real baseline.
Without one, describe current behavior and state that the previous behavior is unconfirmed.
Do not reconstruct inaccessible managed-package internals. Describe verified interfaces, versions,
and limitations, and distinguish repository source from observed org state.

Use inline Mermaid when it explains a material relationship or sequence. Each diagram answers
one question. Aim for 4–8 structural elements or 3–5 sequence participants, splitting larger
diagrams without losing important behavior. Trivial sections need no diagram. Do not add images,
rendering dependencies, or other output files.

The result is three plain Markdown files. Do not add JSON envelopes, required frontmatter,
claims, SHA values, digests, revision numbers, freshness registries, section-verification metrics,
an index file, or a separate report. Git already holds file history. Ordinary links and brief
material unknowns are sufficient; do not apply report-envelope fields to this set.

## Author and verify

1. Read relevant repository instructions and resolve the topic, boundaries, and destination.
   The Developer is already on the proper work branch. This command adds no branch creation,
   Git bootstrap, or separate Git gate.
2. Inspect actual source, metadata, configuration, relevant tests, and requirements once.
   Build one working picture of components and scenarios in task context, without an inventory file.
3. Separate what the sources establish from what remains unknown. Keep material unknowns near
   the affected explanation; never invent behavior, rationale, or test results to fill a section.
4. Write or update `components.md`, then `flows.md`, then `overview.md` in this one task.
   This order does not require three agents or sessions.
5. Review names, links, contracts, effects, transaction boundaries, rationale, and state across
   the complete set. Check the diff and permitted destinations. Confirm new files are visible
   to Git, without changing the ignore rules for `output/`.
6. If a Mermaid renderer is already available, check the diagrams. Otherwise report source
   review without rendering. Document consistency and diagram rendering do not prove runtime behavior.
7. Apply the existing [Git Workflow](../git-workflow/SKILL.md) for a scoped local commit after
   proportional verification. Preserve unrelated changes and make no empty commit for a no-op.
   Do not automatically push, create or update a PR, merge, publish, or start another documentation workflow.
8. Return the overview link, a brief result, actual local commit outcome, and material gaps.
   Do not repeat the full documents or generate a separate report.
