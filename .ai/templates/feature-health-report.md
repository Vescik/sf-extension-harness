# Template: Feature Health Report

<!--
Used by skill: check-feature-coverage (invoked via /feature-health, or by the Test Strategist).
Output location: output/feature-health/<featureId>.md
Source: historical design blueprint section 13 (git tag design-history). All 6 sections are mandatory — a section with no
content gets an explicit "none", it is never silently dropped.
-->

# Feature Health: <Feature title>

## 1. Header

- Feature ID: `<featureId>`
- Feature URL: `<URL from the current ADO source, or unavailable>`
- Title: `<title>`
- Type: `Feature Health report`
- Status: `draft`
- Scope: `<Feature/BRD requirements and child Stories assessed>`
- BRD attached: `<yes — analyzed in full | no>`
- Generated on: `<date>`
- Sources: `<Feature, child Story and BRD references; source revisions and completeness>`
- Verification: `<source and coverage checks performed, observed results, and remaining gaps>`

## 2. Coverage summary

<!--
State the coverage result and PASS / WARN / BLOCKED / INCOMPLETE verdict from the skill.
Keep report review status separate from this verdict. Include the requirement-to-Story matrix
with source references and rationale. New prose is English/STE; preserve original source
quotations in their source language and identify them as evidence.
-->

## 3. Gaps

<!-- Requirements from the Feature/BRD with no covering User Story. If none: "None found." -->

- `<requirement>` — not covered by any Story

## 4. Orphans

<!--
Stories with no clear link to the Feature/BRD. Mark explicitly: this is a signal to check,
not automatically an error (e.g. a technical/enabler story is legitimate).
-->

- `<Story ID> - <title>` — `<why it does not map to any requirement>`

## 5. Open questions

<!-- Ambiguities on either side (Feature/BRD wording or Story wording). -->

## 6. Early warnings

<!--
Conflicts with limitations recorded on approved Knowledge Entries, if any Story touches a known managed
package limitation. Catching this here is cheaper than after the design phase.
-->
