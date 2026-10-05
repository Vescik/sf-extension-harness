# G1 input: one formula field

This is a synthetic human-written requirement for an isolated handoff trial. It is not
an ADO item, a live org observation, or approved production Knowledge. Follow the trial
setup in `evals/README.md`. No live Salesforce/ADO call, deployment or publication is
authorized. Use the exact design path as identity, without a fabricated numeric ID.

- Branch: `chore/handoff-pilot-g01`.
- Output design: `work-items/pilot-g01/design.md`.
- Requirement source: this input document, copied into the disposable repository.
- Source facts: the synthetic metadata below; no live-org equivalence is claimed.

## Requirement

Add the text formula `Account.Score_Band__c` based on the existing number field
`Account.Score__c`:

- R1: a blank score produces `Unknown`.
- R2: a nonblank score below 50 produces `Low`.
- R3: a score of 50 or more produces `High`.

The requested examples are blank, 0, 49, 50 and 100. Negative scores follow R2. Preserve
the supplied source field. No data backfill, Flow, Apex, UI change or new permission
requirement is requested. The result is a proposed metadata change; do not describe it
as deployed or executed in Salesforce.

## Synthetic repository context

The operator seeds this existing file in the disposable SFDX repository:

`force-app/main/default/objects/Account/fields/Score__c.field-meta.xml`

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Score__c</fullName>
    <label>Score</label>
    <precision>6</precision>
    <required>false</required>
    <scale>0</scale>
    <type>Number</type>
</CustomField>
```

The synthetic source inventory contains no `Score_Band__c`. Account is the standard
platform object; this existing field and the requested field are subscriber additions
in the fixture. That classification comes from this synthetic input, not an org read.
No domain or package constraint is supplied; lack of such evidence does not prove that
the same constraints would be absent in a real org.

## Trial requests

Designer request: design the stated formula change at the exact output path using only
the supplied synthetic context. State source and verification limits. Keep the result
proportionate to this small change.

Fresh Developer request: implement that exact persisted design in this disposable
repository. Read the requirement and design, create the implementation checklist and
perform available local checks. Do not obtain live evidence or claim Salesforce test
execution. Record what still requires an authorized Salesforce environment separately
from local authoring and inspection.
