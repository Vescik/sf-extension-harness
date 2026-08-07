---
description: Flow engineering rules — bulk safety, fault handling, Flow-vs-Apex choice, versioning, testing. Loaded for Flow metadata.
applyTo: "**/*.flow-meta.xml"
---

# Flow Rules

Apply these when authoring or reviewing Flows. Package boundaries in
`managed-package.instructions.md` always take precedence.

- **SF-FLOW-001 — bulk-safe by design.** Record-triggered flows run in bulk contexts:
  no queries or DML inside loops, collection processing throughout, and stated limit
  assumptions for every path.
- **SF-FLOW-002 — every fault path is handled.** No swallowed faults: fault connectors
  lead to an observable outcome (error record, notification, or surfaced message)
  without exposing secrets or sensitive record data.
- **SF-FLOW-003 — choose Flow deliberately.** Document why Flow rather than Apex (or the
  reverse) fits the transactionality, volume, error handling, and package constraints of
  the change. On a package-owned or ownership-unknown object, new save-transaction
  automation additionally needs the extension-point evidence required by `MP-EXT-001`.
- **SF-FLOW-004 — version intentionally.** New flow versions state what changed and why;
  deactivations are explicit decisions recorded in the work item, never side effects.
- **SF-FLOW-005 — test against acceptance criteria.** Every flow change carries a test
  plan (scenarios, bulk case, fault case) tied to the work item's acceptance criteria.
