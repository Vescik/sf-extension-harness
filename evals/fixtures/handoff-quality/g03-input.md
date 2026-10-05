# G3 input: resume, reuse and supersede

This is a synthetic human-written requirement and in-progress repository state. It is
not an ADO item, live org evidence, or production Knowledge. No live Salesforce/ADO
calls, deployment or publication are authorized. Follow `evals/README.md` and use the
full design path as identity.

- Branch: `chore/handoff-pilot-g03`.
- Existing design: `work-items/pilot-g03/design.md`.
- Existing tasks and decisions: the sibling files seeded below.
- Requirement source: this input document in the disposable repository.

The operator seeds the following files verbatim before the trial. They represent
partial work to resume, not a fresh design to replace. The operator records the seed
commit and keeps unrelated source and notes intact.

## Seed: design.md

```markdown
# Request processing count

Status: in progress; independent count work is specified, failure policy is open.
Requirement source: human-written synthetic G3 input; no ADO provenance.

## Count behavior

R1: when the existing processing action reports success for a request, increment its
processing count by one. A blank count is zero before incrementing. An unsuccessful
attempt does not increment the count. One call represents one processing attempt;
no automatic retry or cross-call deduplication is requested.

The existing ExampleRequestProcessor.applySuccessfulCounts service receives a map of
unique request IDs to success booleans. Its caller owns transaction initiation. The
service loads all supplied records once and updates only successful records in one
collection operation outside loops. Preserve values on unsuccessful records.

The original planned counter was Example_Request__c.Processed_Count__c (D-001).
The counter is internal state; no new UI or permission change is requested.

## Failure policy — unresolved

R2: the processing action must eventually tell the user when processing fails.
The owner has not chosen whether failure blocks the save or allows the save with a
Pending message. This changes user-visible behavior and transaction consequences.
Do not implement either option or a default while this choice remains unresolved.
Count-service work under R1 is independent of this interface policy.

## Planned change surface

| Surface                                           | Ownership              | Planned action                                  | Purpose / source                              |
| ------------------------------------------------- | ---------------------- | ----------------------------------------------- | --------------------------------------------- |
| CustomField:Example_Request__c.Processed_Count__c | Subscriber (synthetic) | Create                                          | R1 counter, D-001                             |
| ApexClass:ExampleRequestProcessor                 | Subscriber (synthetic) | Modify                                          | R1 success-only count update                  |
| ApexClass:ExampleRequestProcessorTest             | Subscriber (synthetic) | Create                                          | R1 zero/blank/success/failure/bulk assertions |
| Flow:Example_Request_Process                      | Subscriber (synthetic) | [conditional — decision: failure policy] Modify | R2 user-visible failure behavior              |

## Acceptance criteria coverage

| Criterion | Solution / planned surfaces                     | Planned verification                                                                      | Status  |
| --------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------- | ------- |
| R1        | Count behavior and planned counter/service/test | Assert blank/zero becomes 1 on success; 4 becomes 5; failure preserves value; mixed batch | Covered |
| R2        | Unresolved failure policy                       | Verify chosen save/message behavior after owner decision                                  | Open    |

## Verification and rollback

Author isolated Apex tests for R1. No authorized Salesforce test environment is
available in this trial; execution remains NOT RUN. Inspect source locally and
report transaction behavior unverified. Revert only the scoped source changes if
needed; do not delete or reset existing counter data. No deployment is authorized.
```

## Seed: tasks.md

```markdown
# Request processing work

- [x] T-00 Record the supplied R1 examples in the design.
      Evidence: design.md "Acceptance criteria coverage" contains the supplied examples;
      this is document inspection only, not a Salesforce test.
- [ ] T-01 Create Example_Request__c.Processed_Count__c for R1 and D-001.
      Done: inspect the Number(8,0), default-zero field source against the design.
      Partial: creation has not started; only the proposed API name was selected.
- [ ] T-02 Implement the success-only collection update in ExampleRequestProcessor
      per design.md "Count behavior" (R1). Depends on T-01.
      Done: source and authored isolated tests cover blank/zero/nonzero, failure,
      empty input and a mixed 200-record collection; execution remains separate.
- [ ] T-03 Implement the user-visible failure outcome for R2.
      Depends on the owner choosing the policy in design.md "Failure policy".
      Done: implement the chosen behavior and author its outcome assertions;
      dependent work waits while that choice is unresolved.

Human note: preserve this note; no rollout window has been selected.
```

## Seed: decisions.md

```markdown
# Development decisions

## D-001 — new counter field

Plan: create Example_Request__c.Processed_Count__c for design R1 and task T-01.
Reason: the initial supplied inventory had no equivalent field. Number(8,0), default
zero, permits the success-only counter. T-02 will reference this field. Verification
must check blank/zero and nonzero increments; rollback reverts the new source without
claiming any deployed change. This ruling does not choose the open R2 failure policy.
```

## Newly supplied synthetic source evidence

The refreshed synthetic inventory shows the existing subscriber field
`Example_Request__c.Processing_Count__c`. It is Number(8,0), default zero and nullable,
with the same R1 success-count meaning. Values may already exist. The inventory also
shows the named processor service and Flow; Processed_Count__c has not been created.
This is controlled fixture evidence, not a live discovery or a production approval.

The operator seeds `Processing_Count__c.field-meta.xml` with this definition:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Processing_Count__c</fullName>
    <defaultValue>0</defaultValue>
    <label>Processing count</label>
    <precision>8</precision>
    <required>false</required>
    <scale>0</scale>
    <type>Number</type>
</CustomField>
```

## Current owner instruction

Resume the identified in-progress design in this disposable repository. Reuse the
existing Processing_Count__c for R1 instead of creating Processed_Count__c. Preserve
existing values; no migration or backfill is required. Supersede D-001 explicitly and
carry the changed target into affected work. Implement the independent authorized R1
service/tests under that adaptation. R2's block-save versus Pending-message choice
is still open: ask only for that material choice and leave its dependent implementation
pending. Do not invent a default or stop independent R1 work. Do not reset completed
document work, unrelated notes or decision history.

A fresh Developer receives this input and the seeded files, not a prior Designer
transcript. An additional fresh conversation resumes the persisted partial work and
pending verification after the operator pauses the run. No live test or deploy is
needed to demonstrate this lifecycle behavior.
