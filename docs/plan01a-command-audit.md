# Plan 01a command discovery — historical pre-native audit

This table records the earlier source-branch discovery, not the current native acceptance status.
Plan 01a's native implementation is based on main `5f01811`; see
[the native operation contract](native-salesforce-operations.md) and [current handoff](plan01a-handoff.md).
Statements below that latest was held describe the pre-native terminal lane, which remains guarded.

Authority: plan 01a, 2026-09-28; historical discovery baseline `e329fa5`. Installed CLI 2.151.7, Node 24.20.0.
No org command was executed. Evidence: installed `oclif.manifest.json` and command sources;
`sf force data soql query --help` confirms space-separated legacy aliases. Before plan 01,
Developer's role guard accepted direct CLI without a command catalog; the safety hook asked
for real deploys. Thus the prior surface was open-ended, not a finite promised command set.
This review restores bounded, understood paths, not every possible installed plugin action.

## Results

Twenty-one additional command paths are classified. The static alias map also recognizes
189 exact registered spellings of reviewed implementations, including colon and space forms.
The map is static source code, never inferred from customer-installed plugins at runtime.
`--root-type-with-dependencies` accepts values on classified nonprod retrieve only; the production
retrieve flag set is unchanged. Source deletion performs a deployment, so both modern/legacy
spellings now use the real-deploy confirmation gate unless check-only is selected.

`tests/test_plan01a_nonprod.py` exercises each added path through both hook processes on
all four environments and gates a non-networked executor. Other-role denial, cache/parent/hub
aliases, retrieve flags, confirmation and identity errors have separate regressions.
Policy acceptance is not proof of a successful Salesforce operation with real input files.

## Installed org-facing command table

Each row is a canonical installed command. Its registered aliases share its implementation
when present in `COMMAND_ALIASES`; unlisted aliases remain denied. `target` means explicit
org/default; `hub` means Dev Hub/default. `cache` and `parent` are resolved additionally.
`existing` covers classification already present, not a host acceptance result. Latest and
flag-file restrictions apply even to allowed rows. Tests use synthetic orgs only.

| Command | Actual target source | At e329fa5 | Now / test or remaining prerequisite |
|---|---|---|---|
| `project convert source-behavior` | target | denied path | held: further semantics/permission review required |
| `project delete source` | target | denied path | restored; four-env process matrix |
| `project delete tracking` | target | denied path | restored; four-env process matrix |
| `project deploy cancel` | target / job cache (family-specific) | allowed path | existing + reviewed spellings; regression suite; latest NOT RESTORED (host binding missing) |
| `project deploy preview` | target | allowed path | existing + reviewed spellings; regression suite |
| `project deploy quick` | target / job cache (family-specific) | allowed path | existing + reviewed spellings; regression suite; latest NOT RESTORED (host binding missing) |
| `project deploy report` | target / job cache (family-specific) | allowed path | existing + reviewed spellings; regression suite; latest NOT RESTORED (host binding missing) |
| `project deploy resume` | target / job cache (family-specific) | allowed path | existing + reviewed spellings; regression suite; latest NOT RESTORED (host binding missing) |
| `project deploy start` | target | allowed path | existing + reviewed spellings; regression suite |
| `project deploy validate` | target | allowed path | existing + reviewed spellings; regression suite |
| `project reset tracking` | target | denied path | restored; four-env process matrix |
| `project retrieve preview` | target | allowed path | existing + reviewed spellings; regression suite |
| `project retrieve start` | target | allowed path | existing + reviewed spellings; regression suite |
| `data bulk results` | target | denied path | restored; four-env process matrix |
| `data create file` | target | denied path | restored; four-env process matrix |
| `data create record` | target | allowed path | existing + reviewed spellings; regression suite |
| `data delete bulk` | target | allowed path | existing + reviewed spellings; regression suite |
| `data delete record` | target | allowed path | existing + reviewed spellings; regression suite |
| `data delete resume` | target / job cache (family-specific) | denied path | held: further semantics/permission review required; latest NOT RESTORED (host binding missing) |
| `data export bulk` | target | allowed path | existing + reviewed spellings; regression suite |
| `data export resume` | target / job cache (family-specific) | denied path | held: further semantics/permission review required; latest NOT RESTORED (host binding missing) |
| `data export tree` | target | allowed path | existing + reviewed spellings; regression suite |
| `data get record` | target | allowed path | existing + reviewed spellings; regression suite |
| `data import bulk` | target | allowed path | existing + reviewed spellings; regression suite |
| `data import resume` | target / job cache (family-specific) | denied path | held: further semantics/permission review required; latest NOT RESTORED (host binding missing) |
| `data import tree` | target | allowed path | existing + reviewed spellings; regression suite |
| `data query` | target | allowed path | existing + reviewed spellings; regression suite |
| `data resume` | target / job cache (family-specific) | allowed path | existing + reviewed spellings; regression suite |
| `data search` | target | denied path | restored; four-env process matrix |
| `data update bulk` | target | denied path | restored; four-env process matrix |
| `data update record` | target | allowed path | existing + reviewed spellings; regression suite |
| `data update resume` | target / job cache (family-specific) | denied path | held: further semantics/permission review required; latest NOT RESTORED (host binding missing) |
| `data upsert bulk` | target | allowed path | existing + reviewed spellings; regression suite |
| `data upsert resume` | target / job cache (family-specific) | denied path | held: further semantics/permission review required; latest NOT RESTORED (host binding missing) |
| `force data bulk delete` | target | allowed path | existing + reviewed spellings; regression suite |
| `force data bulk status` | target | denied path | restored; four-env process matrix |
| `force data bulk upsert` | target | allowed path | existing + reviewed spellings; regression suite |
| `org auth show-access-token` | target | denied path | held: credential handling remains human-owned |
| `org auth show-sfdx-auth-url` | target | denied path | held: credential handling remains human-owned |
| `org auth show-user-password` | target | denied path | held: credential handling remains human-owned |
| `org create agent-user` | target | denied path | held: further semantics/permission review required |
| `org create sandbox` | target | allowed path | existing + reviewed spellings; regression suite |
| `org create scratch` | hub | allowed path | existing + reviewed spellings; regression suite |
| `org delete sandbox` | target + sandbox parent | allowed path | existing + reviewed spellings; regression suite |
| `org delete scratch` | target + Dev Hub / sandbox relation | allowed path | existing + reviewed spellings; regression suite |
| `org disable tracking` | target | denied path | restored; four-env process matrix |
| `org display` | target | allowed path | existing + reviewed spellings; regression suite |
| `org enable tracking` | target | denied path | restored; four-env process matrix |
| `org list metadata` | target | denied path | restored; four-env process matrix |
| `org list metadata-types` | target | denied path | restored; four-env process matrix |
| `org open` | target | denied path | held: browser capability remains forbidden |
| `org open agent` | target | denied path | held: browser capability remains forbidden |
| `org open authoring-bundle` | target | denied path | held: browser capability remains forbidden |
| `org refresh sandbox` | target | denied path | restored; four-env process matrix |
| `org resume sandbox` | target / job cache (family-specific) | allowed path | existing + reviewed spellings; regression suite; latest NOT RESTORED (host binding missing) |
| `org resume scratch` | target / job cache (family-specific) | allowed path | existing + reviewed spellings; regression suite; latest NOT RESTORED (host binding missing) |
| `apex get log` | target | allowed path | existing + reviewed spellings; regression suite |
| `apex get test` | target | allowed path | existing + reviewed spellings; regression suite |
| `apex list log` | target | allowed path | existing + reviewed spellings; regression suite |
| `apex run` | target | allowed path | existing + reviewed spellings; regression suite |
| `apex run test` | target | allowed path | existing + reviewed spellings; regression suite |
| `apex tail log` | target | denied path | restored; four-env process matrix |
| `logic get test` | target | denied path | restored; four-env process matrix |
| `logic run test` | target | denied path | restored; four-env process matrix |
| `package1 version create` | target | denied path | held: further semantics/permission review required |
| `package1 version create get` | target | denied path | held: further semantics/permission review required |
| `package1 version display` | target | denied path | held: further semantics/permission review required |
| `package1 version list` | target | denied path | held: further semantics/permission review required |
| `package bundle create` | hub | denied path | held: further semantics/permission review required |
| `package bundle delete` | hub | denied path | held: further semantics/permission review required |
| `package bundle install` | target | denied path | held: further semantics/permission review required |
| `package bundle install report` | target | denied path | held: further semantics/permission review required |
| `package bundle installed list` | target | denied path | held: further semantics/permission review required |
| `package bundle list` | hub | denied path | held: further semantics/permission review required |
| `package bundle uninstall` | target | denied path | held: further semantics/permission review required |
| `package bundle version create` | hub | denied path | held: further semantics/permission review required |
| `package bundle version create list` | hub | denied path | held: further semantics/permission review required |
| `package bundle version create report` | hub | denied path | held: further semantics/permission review required |
| `package bundle version list` | hub | denied path | held: further semantics/permission review required |
| `package bundle version report` | hub | denied path | held: further semantics/permission review required |
| `package convert` | hub | denied path | held: further semantics/permission review required |
| `package create` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package delete` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package install` | target | allowed path | existing + reviewed spellings; regression suite |
| `package install report` | target | denied path | restored; four-env process matrix |
| `package installed list` | target | allowed path | existing + reviewed spellings; regression suite |
| `package list` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package push-upgrade abort` | hub | denied path | held: subscriber targets need separate resolution |
| `package push-upgrade list` | hub | denied path | held: subscriber targets need separate resolution |
| `package push-upgrade report` | hub | denied path | held: subscriber targets need separate resolution |
| `package push-upgrade schedule` | hub | denied path | held: subscriber targets need separate resolution |
| `package uninstall` | target | allowed path | existing + reviewed spellings; regression suite |
| `package uninstall report` | target | denied path | restored; four-env process matrix |
| `package update` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package version create` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package version create list` | hub | denied path | restored; four-env process matrix |
| `package version create report` | hub | denied path | restored; four-env process matrix |
| `package version delete` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package version displayancestry` | hub | denied path | held: further semantics/permission review required |
| `package version displaydependencies` | hub | denied path | held: further semantics/permission review required |
| `package version list` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package version promote` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package version report` | hub | allowed path | existing + reviewed spellings; regression suite |
| `package version retrieve` | hub | denied path | held: further semantics/permission review required |
| `package version update` | hub | allowed path | existing + reviewed spellings; regression suite |
| `force user password generate` | target | denied path | held: credential handling remains human-owned |
| `force user permset assign` | target | allowed path | existing + reviewed spellings; regression suite |
| `force user permsetlicense assign` | target | denied path | held: further semantics/permission review required |
| `org assign permset` | target | allowed path | existing + reviewed spellings; regression suite |
| `org assign permsetlicense` | target | allowed path | existing + reviewed spellings; regression suite |
| `org create user` | target | denied path | held: further semantics/permission review required |
| `org display user` | target | denied path | held: further semantics/permission review required |
| `org generate password` | target | denied path | held: credential handling remains human-owned |
| `org list users` | target | denied path | held: further semantics/permission review required |
| `org list limits` | target | allowed path | existing + reviewed spellings; regression suite |
| `org list sobject record-counts` | target | denied path | restored; four-env process matrix |
| `sobject describe` | target | allowed path | existing + reviewed spellings; regression suite |
| `sobject list` | target | allowed path | existing + reviewed spellings; regression suite |

## Source semantics checked for restored paths

- `plugin-org` metadata/metadata-types uses the selected connection; tracking toggles use the
  selected Org; refresh sandbox uses the selected **parent** Org, including lookups by source
  sandbox name/ID. It never makes a production parent eligible merely because its child is dev.
- `plugin-deploy-retrieve` delete/reset tracking uses selected Org/SourceTracking;
  delete source builds and deploys destructive changes with that Org and a check-only flag.
- `plugin-data` search, create file, update bulk, bulk results and Bulk API v1 status build their
  connection from the required target. Explicit job IDs do not switch to another cached org.
  New bulk resume families use cached connection options; they stay held for further binding work.
- `plugin-apex` log tail and Logic test run/report use the selected connection. Tests remain
  forbidden on prod. `plugin-packaging` install/uninstall reports use selected org; version-create
  list/report use required Dev Hub. Package IDs/request IDs do not grant another target.
- Registered `env:*` aliases invoke the already-reviewed lifecycle implementations, so sandbox
  relation/cache and scratch hub checks are retained. Deploy metadata aliases invoke the same
  deploy job-cache checks and real-deploy confirmation as their canonical paths.

## Unrestored variants and unavailable commands

| Variant | Evidence | Result |
|---|---|---|
| Deploy `--use-most-recent` / `-r` | `DeployCache.resolveLatest` selects a mutable latest key; quick has its own cached target resolution | Held; need host to execute the assessed immutable job and org |
| Sandbox latest `-l`, scratch latest `-r` | Lifecycle cache supplies parent/hub; changing cache changes operation | Held; concrete job/name paths and aliases retain existing relation checks |
| Bulk import/export/update/upsert/delete resume | Family-specific cache resolves connection as well as Job ID | Held; no allowance based only on nonprod `-o` |
| `--flags-dir` | Files inject CLI flags, including target; files can change after evaluation | Held; needs assessed immutable arguments bound to execution |
| `force:source:retrieve`, `force:mdapi:retrieve`, `force:mdapi:retrieve:report`, generic `force:org:create/delete`, `project retrieve resume` | Absent from installed manifests | Unavailable here; not registered as guessed aliases |
| Newly installed/unknown plugins, arbitrary API request commands | Semantics not reviewed | Denied; no blanket nonprod fallback |
| Local-only auth/config/alias/plugin commands | No per-org semantics; can alter identity or credential state | Not added; human setup remains separate |

No claim is made that this partial restoration satisfies full nonprod compatibility. A valid
explicit job can still depend on mutable cache/alias state; existing snapshot controls are
retained, not advertised as atomic execution. The interoperability=false default discrepancy
is excluded by D-038; this implementation does not change default resolution.
