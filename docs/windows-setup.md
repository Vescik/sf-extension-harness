# Windows Setup & MCP Fix — Step by Step

This is the practical runbook for running the brain-core harness on **Windows** in VS Code + GitHub
Copilot. The configured MCP surface is read-only on every platform. The Developer uses direct
`sf`/`sfdx` for reviewed Salesforce deployments and org mutations on `dev`/`uat`/`stage`.
Production CLI permits only verified metadata retrieve; other production reads use the existing
MCP within role limits. Test Strategist cannot target production, including MCP. Every real deploy stops for a fresh
chat confirmation that names the target and scope and warns that changes will be deployed to the
org; dry runs, retrieve, status/report/resume/cancel, and data mutations do not use that gate.

> ADO reads its organization and project from `config\harness.local.json`. A startup error names
> the field to repair. See **Step 4** for configuration, sign-in, and restart instructions.

---

## Step 1 — Prerequisites

Install and confirm each is on `PATH` (open a **new** PowerShell and run the checks):

| Tool | Requirement | Check |
|---|---|---|
| VS Code + GitHub Copilot / Copilot Chat | current stable | — |
| Python | **3.11+**, exposed as **`python`** (python.org installer; this repo uses `python`, not `py -3`) | `python --version` |
| Node.js | **22+** (MCP launchers and the ADO server run on Node) | `node --version` |
| Salesforce CLI | v2 | `sf --version` |
| Git | any recent | `git --version` |
| GitHub CLI | `gh.exe` on PATH | `gh --version`, `gh auth status` |

For GitHub work, the human configures `gh` authentication for the host used by `origin`.
Never paste token output into chat or files; the agent reports missing access without logging in.

If `python --version` fails but `py --version` works, add Python to PATH (re-run the installer →
"Add python.exe to PATH") so plain `python` resolves.

## Step 2 — Get the workspace and open it

```powershell
git clone <your-fork-url> sf-harness-brain-core
code sf-harness-brain-core\sf-harness.code-workspace
```

Open the `sf-harness.code-workspace` (single-root `brain-core`). Trust the workspace only after you
have reviewed it.

## Step 3 — Install dependencies (guided)

From the repo root, run the onboarding script (it checks prerequisites, installs the pinned
dependencies, creates `config\harness.local.json`, collects ADO settings, and walks selected-org
authorization). It is plain Python — no PowerShell execution policy is involved, so it also works
in organizations where `.ps1` scripts are blocked:

```powershell
python scripts\first_launch.py
```

Manual equivalent, if you prefer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
npm ci --ignore-scripts
```

**Then select the `.venv` interpreter** (required): Command Palette → **Python: Select Interpreter**
→ choose `.venv`. The agents run guarded scripts as `python scripts/<name>.py …`, and VS Code's
integrated terminal only resolves `python` to the venv (with `jsonschema`/`PyYAML`) after you select
it. Without this, commands fail with `ModuleNotFoundError: No module named 'jsonschema'`.

## Step 4 — Configure the ADO target and sign-in

Set `ado.organization` and `ado.project` in `config\harness.local.json` as described in Step 5.
Use one organization and project per workspace. Use a separate workspace for another scope.
The no-argument launcher `scripts/start_ado_mcp.mjs` reads this file and checks the ADO scope
before starting the installed vendor MCP. Missing fields, placeholders, invalid origins, or
missing dependencies produce a local startup error before the vendor connects to ADO.

Start `ado-readonly` in VS Code and complete the connector's interactive OAuth sign-in with
your own account. The pinned vendor version 2.8.1 uses this flow by default in VS Code Local.
Azure CLI login is not required. Never store credentials in the local configuration file.

Restart `ado-readonly` after changing the organization or project. The launcher stops the old
process when it detects a scope change. Restarting all VS Code windows is not required.

**Migration:** keep your existing local JSON. The retired `ADO_ORGANIZATION` variable no longer
affects this workspace, even if it contains a different organization. Leave it in place if
other tools use it. Update the launcher, hooks, and MCP configuration together.

## Step 5 — Fill `config\harness.local.json`

This file is **gitignored** — it lives only on this machine and does not sync via git, so you fill
it here on Windows. Set at minimum:

- `ado.organization` — the organization slug, such as `contoso`, without a URL
- `ado.project` — your ADO project (the hook requires every ADO call to carry this)
- `ado.allowedHttpsOrigins` — include `https://dev.azure.com/contoso`, matching your organization
- `ado.releaseQueryId` — your saved release query id (only for release flows)
- For each sandbox under `salesforce.orgs`: `alias`, `expectedInstanceHost`, `expectedOrganizationId`
- `salesforce.review.allowedObjectApiNames` — objects the agent may read; `["*"]` = all objects
  (keep tighter if the org holds sensitive data)

`python scripts\first_launch.py` fills the ADO and sandbox values for you interactively; edit the
file directly only if you skip the script. For a fully manual, zero-assumptions walkthrough see
[setup-zero-to-first-prompt.md](setup-zero-to-first-prompt.md).
When you change the organization manually, replace its old ADO origins too. The script does
this automatically and preserves other approved HTTPS origins.

**Upgrading an existing machine?** Configs written before 2026-08-05 may carry retired keys the
schema now rejects (`first_launch.py` reports schema errors until they are deleted): per-org `allowAgent*`,
`review.allowAnyNonProduction`, `review.maxObjectsPerCall`, `safety.browserSessionApproval`,
`safety.batchDevToolApproval`, `cache.adoItemMaxAgeMinutes`, `cache.testCaseMaxAgeMinutes`,
`workspace.promotedTestsPath`, and the `browser` section — see the migration note in SETUP.md §3.

## Step 6 — Authorize the intended org (review-only)

Salesforce MCP is **review (read-only)** only. Choose the exact target within role limits and
prove its live identity; production reads are permitted through existing tools, while Test
Strategist cannot target production. `salesforce.review.deniedOrganizationIds` remains binding.
The example below is a sandbox login; use the intended org's login URL for another org type.
`IsSandbox=false` alone grants no CLI permission.

```powershell
# alias MUST match the alias in harness.local.json
sf org login web --instance-url https://<MYDOMAIN>--<SANDBOX>.sandbox.my.salesforce.com --alias mpsa_dev_sbx
sf org display --target-org mpsa_dev_sbx --json
#   copy instanceUrl host -> expectedInstanceHost, id -> expectedOrganizationId in the config
```

> **There is no development/write MCP server.** The Developer may use reviewed CLI operations on
> `dev`/`uat`/`stage`, with exact confirmation before each real deploy. Production permits only
> verified CLI metadata retrieve and existing MCP reads within role limits. Confirmation cannot
> authorize a forbidden production operation. See [the channel contract](production-read-only.md).

## Step 7 — Start the MCP servers

When VS Code prompts *"The MCP servers … may have new tools … Start them now?"*, start
**`salesforce`** and **`ado-readonly`** (the only configured servers). When prompted for
the `sf_review_org` input, enter your explicitly selected alias (e.g. `mpsa_dev_sbx`).

## Step 8 — Pre-approve tools (fewer clicks)

- Specific guarded terminal scripts have `chat.tools.terminal.autoApprove` rules. New Git/gh
  capabilities do not add broad auto-approval: native prompts may still appear for local
  stage/commit and requested publication. Do not set global `git=true`/`gh=true` or add shared
  gh/add/commit patterns.
- **MCP read tools** cannot be pre-approved from a committed setting. Run **`Chat: Manage Tool
  Approval`** (Command Palette), expand `salesforce` and `ado-readonly`, and trust all
  their tools at **workspace** scope.

All roles can use all Git/gh commands through [Git Workflow](../.github/skills/git-workflow/SKILL.md).
The only Git-specific validation is commit-message syntax and matching IDs. There are no
branch, path, staging, commit-option, working-directory, or Salesforce/ADO configuration gates.
Install final commit-message validation once per checkout:

```powershell
python scripts/install_git_message_hook.py
```

This local Git hook validates editor/file messages; standard Git hook-skipping options retain
their normal behavior. Push, PR publication/update, merge, and destructive actions require an
explicit human instruction. Native terminal approval may still appear. You do not need to
switch to Git Agent just to commit. Verify both hooks and the effective terminal tool in a
fresh VS Code Local session; parser/unit tests do not prove Windows host behavior.

## Step 9 — Verify

```powershell
.\.venv\Scripts\python.exe scripts\validate_harness.py          # structure OK
```

There is no separate readiness command: Salesforce MCP proves the selected org's live
identity before tool discovery; ADO scope is checked on every tool call. Optional single-org
diagnostic: `.\.venv\Scripts\python.exe scripts\verify_salesforce_org.py --org <alias>`.

Local checks do not prove ADO authentication or read access. In Copilot Chat, read one Work
Item with `/fetch-ado-item itemId=<id>` and one wiki page from the configured project.
The Work Item fetch persists `work-items/<id>-<slug>/ado-context.md` and stops.
Run a Salesforce review separately to verify that connection.

---

## Troubleshooting — the exact errors and their fixes

**First stop for any "Blocked by Pre-Tool Use hook": read `.cache\denials.log`.** Both hooks append
every deny/ask there as one JSON line with timestamp, which hook fired, the role, the tool, and the
exact reason — so you no longer have to guess which guard blocked what:

```powershell
Get-Content .cache\denials.log -Tail 20
```

| Symptom | Cause | Fix |
|---|---|---|
| `ADO configuration error: ...` | Missing or invalid local ADO scope | Correct the named key in `config\harness.local.json`, then restart `ado-readonly` |
| ADO server stops after a configuration edit | Organization or project changed during the session | Check the new scope and restart `ado-readonly` in this workspace |
| `Blocked by Pre-Tool Use hook` on ADO calls | Missing project or a project/URL outside the configured scope | Read the denial reason; supply the configured project and URL |
| ADO sign-in or access fails after local validation passes | Connector authentication or project permission is incomplete | Complete interactive OAuth, then verify access to the configured project |
| Old "ADO runtime organization does not match local policy" error | Partially updated harness | Update the launcher, hooks, and MCP configuration together, then restart `ado-readonly` |
| `Salesforce MCP startup blocked: development mode is disabled on Windows` / `exit code 2` | Stale MCP config — the `salesforce-development` server was removed 2026-07-14 | Pull the latest `main` and reload VS Code; only `salesforce` and `ado-readonly` should be listed |
| A review tool answers `BLOCKED` with `IDENTITY_HOST_MISMATCH` / `IDENTITY_ORG_ID_MISMATCH` / `NOT_SANDBOX` / `ORG_ID_DENIED` | the host signature and live identity disagree, the pins point at a different org, or the org ID is on `deniedOrganizationIds`. `IsSandbox=false` alone is not a failure | Step 5/6: verify the intended identity and correct stale pins; check the denylist and role limits. Sanity-check with `python scripts/verify_salesforce_org.py --org <alias>` |
| `webidl.util.markAsUncloneable is not a function` | Node < 22 | Install Node 22+ (Step 1) |
| ADO call still runs without being scoped / lists all orgs | Known hook-matching gap (see below) | Track the hardening fix; interim, do not rely on the hook to block bare-named MCP tools |

## Known limitations

- **Hook tool-name matching — FIXED.** The safety hook now classifies MCP tools by their bare tool
  token as well as the server prefix, hard-denies org/project enumeration (`core_list_orgs`,
  `core_list_projects`, `list_all_orgs`), and fails closed (asks) on any unrecognized MCP-shaped
  tool. Bare `core_list_orgs`/`run_soql_query`/`deploy_metadata` are no longer bypassable.
- **ADO toolset bounding — FIXED by the stdio switch.** The hosted endpoint did not honor the
  `X-MCP-Toolsets` header, so the harness now runs the local `@azure-devops/mcp` (version-pinned)
  whose `-d work-items wiki search` domain args are actually honored. The local server
  has no server-side read-only mode; read-only remains harness policy (hooks + role guard) — an
  accepted owner decision (2026-07-14). Org-scope + enumeration guards stay the effective control.


## Native one-operation Salesforce tool (plan 01a)

Install the reviewed local VSIX using [the native operation guide](native-salesforce-operations.md) when Developer
needs an unconfigured environment question or supported latest-job operation. The tool owns
native dialogs and one invocation's dispatch; terminal helpers and model-supplied approval or
environment fields remain forbidden. Existing production retrieve-only and MCP role limits apply.
Local tests/build are separate from actual VS Code Local and live-org acceptance; consult the
current plan 01a handoff before claiming either verified.
