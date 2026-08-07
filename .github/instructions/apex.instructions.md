---
description: Apex engineering rules — bulkification, limits, trigger architecture, security, SOQL hygiene, testing, error handling. Loaded for Apex classes.
applyTo: "**/*.cls"
---

# Apex Rules

Apply these when writing or reviewing Apex. Package boundaries in
`managed-package.instructions.md` always take precedence.

- **SF-BULK-001 — bulkify.** No SOQL or DML in loops. Design classes and triggers for
  bulk transactions and collection processing.
- **SF-LIMIT-001 — budgets are explicit.** Review SOQL, DML, CPU, heap, and async limits
  for every automation path; call out limit assumptions in the design.
- **SF-TRIG-001 — one trigger entry point.** One trigger per object with logic delegated
  to a handler or service class. Prevent recursion intentionally.
- **SF-SEC-001 — enforce access.** Declare sharing deliberately and enforce object,
  field, and record access with the mechanism appropriate to the execution context.
  Never rely on UI visibility as authorization.
- **SF-SOQL-001 — prevent injection.** Bind values, allowlist dynamic identifiers, and
  never build SOQL from untrusted ADO, record, or user content.
- **SF-NAME-001 — descriptive PascalCase names.** Use descriptive `PascalCase` class and
  type names. Organization naming conventions, when supplied in `docs/design-guides.md`,
  are authoritative.
- **SF-TEST-001 — assert behavior.** Isolated test data, `@TestSetup` where useful, no
  `SeeAllData=true`, positive/negative/bulk cases, assertions on outcomes rather than
  on coverage.
- **SF-ERR-001 — observable failures.** Preserve actionable error context without
  exposing secrets or sensitive record data. No silent catch blocks.
