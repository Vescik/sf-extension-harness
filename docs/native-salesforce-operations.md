# Native Salesforce operations in VS Code

Plan 01a adds a local VS Code extension for the Developer's one-operation target/environment
selection and reviewed latest-job workflows. Existing Salesforce read MCP and other roles do not
change. Implementation and local tests do not establish successful VS Code Local or live-org
acceptance; see [the current handoff](plan01a-handoff.md) for actual results.

## Install the reviewed package

From a reviewed checkout with Node.js 22+, Python 3.11+ and existing Salesforce CLI authorization:

```text
npm run native:test
npm run native:build
npm run native:package
```

Use VS Code **Extensions: Install from VSIX…** and select the VSIX emitted by the package command.
Reload VS Code, open the single repository/SFDX root as a trusted workspace, choose the **Local**
harness and the **Developer** custom agent. Check Customization Diagnostics for the native tool
and both hooks. This tool is exposed as `sf-harness.salesforce-operations/salesforceOperation`;
the API runtime name is `sf_harness_run_operation` and prompt reference is `salesforceOperation`.
The extension package contains the reviewed runtime. Changing workspace scripts does not update
an installed package: rebuild, review and reinstall it. Never load private execution code from
an arbitrary workspace path. This extension is local; no Marketplace publication is implied.

Verify prerequisites and the selected CLI on each destination. Use the extension's synthetic
tests before a bounded permitted live operation. Never run forbidden commands on production to
check denial. Built-in/default agent mode and hosts without the Local per-agent hooks are not
supported; the tool API does not independently attest the active agent role.

The native job adapter is reviewed for Salesforce CLI **2.151.7** with `@salesforce/core`
**9.2.0** from that installation. A different SDK version is blocked until reviewed; this does
not automatically block ordinary, reviewed non-job CLI commands. Job results are bounded status
summaries, without the CLI's report files, formatters or source-tracking updates.

## Use

The tool takes one object containing only `arguments`, a list of Salesforce subcommand/flag
strings without `sf` or `sfdx`, for example:

```json
{"arguments":["project","retrieve","start","--target-org","team-review","--metadata","ApexClass:Example"]}
```

There is no model-supplied role, workspace, environment, approval, continuation or consent token.
If the target is missing, the extension asks the human to select a locally authenticated identity.
For an authenticated identity without a configured environment, a native dialog asks for
`dev`, `uat`, `stage` or `prod` for this exact operation. A regular Salesforce host can represent
Developer Edition or a Dev Hub; its hostname alone does not remove those choices or override
known configured production. A real deploy has its own exact target/scope
confirmation even after selecting a nonprod environment. Generic tool auto-approval does not
answer either dialog. Chat text does not count as a dialog response.

Canceling or closing a dialog, timeout, malformed replies, identity/config drift or contradictory
classifications stop execution. The answer stays in the invocation's process memory; it never
rewrites `harness.local.json` or creates a consent registry. Every subsequent operation starts a
new assessment. Known production cannot be reclassified by answering dev; prod remains metadata
retrieve only. Other production reads still use existing MCP within role limits. Test Strategist
still cannot target production, including MCP; its accepted instruction-level restriction is unchanged.

## Jobs and direct terminal use

Supported latest selectors are resolved once to an explicit job and controlling org. The packaged
job executor checks that identity and uses the selected ID; it must not reselect a job from changed
CLI cache. Parent/Dev Hub identities and production restrictions still apply. Scratch-org resume
currently remains denied: its reviewed SDK path cannot preserve the required execution binding.
Do not claim all latest families supported or bypass this through ordinary CLI.
Native `org delete sandbox` and `org delete scratch` (including aliases) also remain denied:
generic CLI reloads the parent/Dev Hub relation after assessment, so pinning only the child cannot
bind the actual controller. No private deletion adapter was added. Existing terminal policy is
unchanged; native denial is not permission to work around a terminal denial. Unsupported job
families, flags or cache formats fail closed; a new CLI plugin is not automatically permitted.
See [the command discovery record](plan01a-command-audit.md) for the earlier catalog and the handoff
for the native implementation's actual tested families.

Reviewed direct terminal commands remain available to Developer when the ordinary policy can
fully resolve them. Unknown environments and mutable latest selectors require the native tool.
Never work around a denial by launching `salesforce_operation_session.py`, `salesforce_job_selection.py`
or `salesforce_job_executor.mjs` from a terminal, passing approval/environment flags, copying auth,
rewriting caches or patching an installed CLI. These private files and the extension/package are
root of trust. Workspace Maintainer edits require the existing human confirmation boundary;
no delivery role gains permission to edit or launch them.

## Evidence and API provenance

Repository tests cover admission, dialog/protocol behavior and synthetic dispatch. Packaging
checks cover the reviewed runtime included in the artifact. They do not prove real VS Code UI,
hook invocation, installed CLI/SDK compatibility or live Salesforce results. Record those separately
on the destination and report an unrun case as NOT VERIFIED.

Tool registration follows the [VS Code Language Model Tool API](https://code.visualstudio.com/api/extension-guides/ai/tools).
The full agent reference follows [VS Code's extension reference naming](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/contrib/chat/browser/tools/languageModelToolsService.ts).
Per-agent enforcement uses [Local hooks](https://code.visualstudio.com/docs/agents/reference/hooks-reference).
