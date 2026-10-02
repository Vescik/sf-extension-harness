# Wiki publication

Use `/publish-wiki` with the Developer in VS Code Local when you want to publish existing
repository documentation. The request includes the necessary page and navigation updates.
For delivery documentation, it also includes the existing Story link. It does not start a
Salesforce deployment or change handover and Knowledge contracts.

```text
/publish-wiki docs/solutions/invoice-approval/
/publish-wiki work-items/1234-invoice-approval/technical-documentation.md
```

You can name an existing wiki or path to resolve the destination. A solution needs no Work Item.
The [publication skill](../.github/skills/publish-wiki/SKILL.md) owns the procedure.
Author or update source files with `/document-solution` or `/document-metadata-change` first,
or request authoring and publication together. Publication uses those files and retains their format.

## Current solution pages

One business solution has one stable local directory and three wiki pages:

| Repository source | Wiki destination |
|---|---|
| `docs/solutions/<slug>/overview.md` | `Solutions/<Business domain>/<Solution>` |
| `docs/solutions/<slug>/flows.md` | `Solutions/<Business domain>/<Solution>/Flows` |
| `docs/solutions/<slug>/components.md` | `Solutions/<Business domain>/<Solution>/Components` |

The solution parent is the overview. The domain index links to it. Home, Solutions, and domain
indexes provide shared navigation, not a fourth document for each solution. Domains come from
actual content. Cross-domain solutions have one main location, with links from other domains.
An existing solution retains its address even outside this tree.

Later Stories update the same set. The Developer maintains relevant passages when an assigned
change affects documented behavior, configuration, limitations, or components. A refactor with
no documentation impact does not need a date-only edit. Publication still needs an explicit request.

Local files can describe implemented work before deployment. Current solution wiki pages describe
production-deployed behavior. Delivery context or your statement can establish deployed scope.
A merge, latest `main`, and a closed Story do not establish that fact. If the files include a later
change, the Developer prepares the correct version or reports the gap before replacing current pages.
This requires no mandatory org read, SHA, approval ledger, or new status registry.

## Delivery documentation and links

`work-items/<id>-<slug>/technical-documentation.md` remains the document for one delivery.
It can be published before deployment for handover. Publication preserves its existing format and
adds or confirms the Story's link to that page. A local file alone does not clear `Missing Wiki Link`.
Use the single published branch established by live wiki metadata. The Story artifact relation has
no branch selector, so publishing a delivery page to another branch cannot establish its handover link.
Unknown or ambiguous published-branch metadata leaves that operation incomplete.

Solution pages can link to Stories in their text. They do not automatically add Wiki relations that
compete with the delivery document used by release handover. Existing duplicate or competing links
are reported for resolution. Handover keeps its existing selection and missing-link behavior.
Optional release notes are a short index of changes and links, not copies of the three pages.

## Existing content, conflicts, and results

Before a write, the Developer reads complete live target pages and their relevant navigation.
Search snippets and sanitized cache content cannot supply a write base. Manual edits are reconciled
with durable sources, and unrelated content remains in place. Wiki edits do not trigger automatic
repository synchronization.

The existing `ado-readonly` connector retains its name. Its publication adaptation uses the ETag
returned with the complete read for a conditional update. ETag is transport data, not a user-facing
revision or an agent-maintained registry. A changed page produces a conflict.
The Developer reads it again and applies only compatible changes. Overlapping edits require a
concrete content decision. The workflow never retries a stale overwrite blindly.

Read-back checks verify content and links. Identical pages, index entries, and Story links need no
write. Results identify created, updated, and unchanged pages. A failed page or Story link is reported
separately, even when other pages succeeded. Resuming reads uncertain results and retries only the
unfinished scope.

Only the Developer's requested publication gains these narrow ADO writes. Search remains read-only.
Other roles gain no publication, work-item editing, or unrestricted ADO access. ADO scope comes from
`config/harness.local.json`; terminal ADO and raw HTTP remain outside the workflow.

## Gradual migration

New solutions use the three-page structure. Existing areas are inventoried and adapted when requested,
starting with active solutions. Preserve existing solution addresses and delivery-document links.
Add missing Flows/Components beside the existing parent and link it from the relevant domain index.
Do not mark the entire wiki legacy or require an archive rewrite before publishing a new solution.

Retirement updates the description and navigation without removing historical addresses. A physical
move needs an explicit migration scope and link checks. Whole-wiki inventory, batch estimates, and
bulk migration are separate work.

## Verification boundary

Local validation can establish instruction, scope, and connector behavior against fixtures.
The VS Code Local pilot must separately prove creating a new solution, updating the same three
pages, preserving manual edits, handling conflicts and partial failure, and linking a delivery page.
Implementation alone does not establish live wiki permissions, remote publication, or migration.
