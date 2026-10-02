# G2 input: Flow, bulk Apex and per-input errors

This is a synthetic human-written requirement. It is not an ADO item, a live org
observation, or approved production Knowledge. Follow `evals/README.md`; no live
Salesforce/ADO call, deployment or publication is authorized.

- Branch: `chore/handoff-pilot-g02`.
- Output design: `work-items/pilot-g02/design.md`.
- Requirement source: this input document in the disposable repository.
- Evidence scope: only the synthetic source inventory and behavior described here.

## Supplied synthetic metadata

The operator materializes this representative inventory in the disposable SFDX source
tree. All custom surfaces below are fixture-owned subscriber metadata, not observed org
metadata. The object allows existing automation to update its records in this fixture;
that assumption is not a production access assessment. No new permissions are requested.

| Surface | Supplied definition |
| --- | --- |
| `Example_Request__c` | Custom object, Name is Text |
| `Rush__c` | Checkbox, default false |
| `Requested_At__c` | Optional DateTime, UTC in all test data |
| `Escalate_At__c` | Optional DateTime, existing deadline |
| `Deadline_Error__c` | Existing Text(255), internal operations error display |
| `Description__c` | Optional Text(255), unrelated editable value |
| `Rush_Setting__mdt.Interval_Hours__c` | Number(3,0) on a custom metadata type |
| `Rush_Setting.Default` | Supplied configuration record, interval 4 |
| `Flow:Example_Request_Deadline` | Existing active after-save record-triggered Flow, create and update, action `RequestDeadlineAction` |
| `ApexClass:RequestDeadlineAction` | Existing invocable entry point; receives the current request ID plus create/old-rush context |
| `ApexClass:RequestDeadlineService` | Existing computation seam described below; no query or DML |

Representative field metadata, relative to
`force-app/main/default/objects/Example_Request__c/fields/`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Escalate_At__c</fullName>
    <label>Escalate at</label>
    <required>false</required>
    <type>DateTime</type>
</CustomField>
```

The existing Flow's synthetic wiring is: after-save start on create/update, an
eligibility decision, the invocable Apex action, then an end node. There is no Flow
Update Records element, record loop or external action. Complete and inspect the
changed Flow XML against this wiring; this description is not claimed to be a deployed
Flow definition. Existing source scaffolding may be incomplete and must be reported as
such, not mistaken for a working implementation.

## Required behavior

- R1: for a new rush request, or a false-to-true Rush transition, set the deadline to
  Requested_At plus the configured four hours, only if no deadline exists.
- R2: preserve every existing deadline. Ignore standard requests and unrelated updates.
  A write of the deadline or error field must not cause repeated processing.
- R3: for an otherwise eligible request with missing Requested_At or missing, zero or
  negative configuration, return an explicit error for that input and do not write its
  deadline. Other valid inputs still produce and persist their own results.
- R4: the action returns one result per input in the same order, including unchanged
  and failed inputs. Match results by input position and request ID; do not sort away
  the association. Inputs contain unique valid synthetic request IDs.
- R5: process a 200-record mixed batch without per-record queries or DML. No customer
  notification, async retry or additional automation is requested.

## Service, writer and error boundary

Keep a separately testable computation seam in `RequestDeadlineService`. Its logical
input is a collection of snapshots: request ID, is-create, previous Rush value, current
Rush, Requested_At and existing Escalate_At; configuration is a separate nullable hours
value. Its output is an ordered collection with request ID, outcome (`READY`,
`UNCHANGED`, `ERROR`), optional deadline, error code and message. Exact private Apex
types and helper names are implementation choices. The service performs no SOQL/DML.

The invocable `RequestDeadlineAction` is the only writer. It reads the current records
and configuration in bounded collection operations, calls the service, builds one
update collection and uses partial-success DML outside loops. For `READY`, write the
deadline and clear a prior Deadline_Error. For `ERROR`, preserve the deadline and write
the error code/message to the existing Deadline_Error field. `UNCHANGED` creates no
update. Do not add writes to the Flow or the computation service.

Use `MISSING_REQUESTED_AT` for absent time and `INVALID_CONFIGURATION` for invalid
configuration. For otherwise eligible inputs, invalid configuration takes precedence
when both are wrong. A saved validation error must be visible in Deadline_Error to
internal operations. Return the same error in the invocable result. If a per-record
DML operation fails, return `WRITE_FAILED` with an actionable message for that input;
do not claim its deadline or error text was persisted. Do not throw one input's normal
validation/DML failure across the whole batch or hide it as success. Flow receives the
action's per-input outputs; persistent error display is owned by the Apex writer, not
a new Flow error writer. Transaction-wide platform faults remain a separate unverified
execution risk and are not simulated as successful partial DML.

## Controlled examples and tests to author

Use synthetic times, never real business records. A requested time of
`2026-01-01T10:00:00Z` with four hours should produce `2026-01-01T14:00:00Z`.
Include create-rush, false-to-true, standard request, unrelated update, existing deadline,
missing time, each invalid configuration value, empty collection, and ordered
valid/invalid/valid inputs. Include a mixed 200-input case and assertions about the
action's results and persisted deadline/error values. Test the pure service directly;
use an isolated fixture or bounded injection seam for action configuration and writer
failure, without `SeeAllData=true` or production custom metadata dependence.

Author Apex test methods and inspect their assertions. The trial has no authorized
Salesforce test environment. Report Apex execution as NOT RUN, leave execution-dependent
tasks unchecked, and label transaction, platform limits and deployed Flow behavior as
unverified. Available local source/XML inspection is not an Apex test pass.

## Trial requests

Designer: specify this behavior and the Flow/service/action boundary at the exact design
path, using supplied synthetic context. Identify any residual material gaps explicitly.

Fresh Developer: implement that persisted design only in the disposable repository,
creating tasks before source edits. Preserve a useful split between authored code/tests
and unavailable execution proof. No deploy or live mutation is required to finish the
agent-behavior trial.
