# Zero to First Prompt — complete manual setup walkthrough

This guide assumes **nothing**: a fresh Windows machine, no tools installed, and no prior
knowledge of this workspace. Every step shows the exact command, what success looks like, and
what to do when it fails. It is the manual alternative to the guided script
(`python scripts/first_launch.py`) — you can switch to the script at any point after Part 2.

macOS/Linux users: the flow is identical; path and activation differences are called out inline.

**What you are setting up.** This repository is a governed GitHub Copilot workspace ("harness")
for Salesforce development around a managed-package environment. It gives Copilot five specialized
agents, guarded read-only access to Azure DevOps and a Salesforce sandbox, and safety rails that
fail closed. Nothing here contains credentials; you authorize everything locally in Parts 6–7.

**Scope (important).** The configured MCP surface is read-only. The Developer uses direct
Salesforce CLI for deploys and org mutations. Every real deploy requires fresh chat confirmation
with its target, scope, and a warning that changes will be deployed to the org; dry runs, retrieve,
status/report/resume/cancel, and data mutations do not. Browser automation tooling is unavailable (see
`docs/compatibility.md`).

---

## Part 1 — Install the tools

Open **PowerShell** (Start menu → type `powershell`). After each install, **close and reopen**
PowerShell before running the check — PATH changes only apply to new windows.

### 1.1 Git

- Download from <https://git-scm.com/download/win> and run the installer with default options,
  or with winget: `winget install --id Git.Git -e`
- Check: `git --version` → prints something like `git version 2.45.0.windows.1`

### 1.2 Python 3.12

- Download the latest 3.12.x from <https://www.python.org/downloads/windows/> and run it.
- **On the first installer screen tick "Add python.exe to PATH"** — this checkbox is off by
  default and skipping it is the most common setup mistake.
- Or with winget: `winget install --id Python.Python.3.12 -e`
- Check: `python --version` → `Python 3.12.x`
- If `python --version` opens the Microsoft Store or fails while `py --version` works: re-run
  the installer → Modify → tick the PATH option, or disable the Store alias under
  Settings → Apps → Advanced app settings → App execution aliases.
- The supported baseline is Python 3.11+; CI certifies 3.12, so install 3.12.

### 1.3 Node.js 24

- Download the Node 24 (LTS) Windows installer from <https://nodejs.org/> and run it with
  default options, or: `winget install --id OpenJS.NodeJS.LTS -e`
- Check: `node --version` → `v24.x.x` (22.19+ is the minimum; 24 matches `.nvmrc` and CI), and
  `npm --version` prints a version.

### 1.4 Salesforce CLI

- Download the Windows x64 installer from
  <https://developer.salesforce.com/tools/salesforcecli> and run it, or:
  `winget install --id Salesforce.sf -e`
- Check: `sf --version` → `@salesforce/cli/2.x.x ...`

### 1.5 VS Code + GitHub Copilot

- Install VS Code from <https://code.visualstudio.com/> (or `winget install -e --id Microsoft.VisualStudioCode`).
- Open VS Code → Extensions view (`Ctrl+Shift+X`) → install **GitHub Copilot** and sign in with
  your GitHub account when prompted (your organization must have a Copilot license for you).
- Check: the Copilot Chat icon appears in the VS Code sidebar/title bar.

If your organization blocks installers or winget, request Git, Python 3.12, Node 24, Salesforce
CLI, and VS Code through your IT software catalog — no admin-only or unusual components are used.

---

## Part 2 — Get the workspace

Pick a folder you own (example: `C:\dev`) and clone the repository. Your team lead gives you the
repository URL and access.

```powershell
cd C:\dev
git clone <repository-url> sf-harness-brain-core
code sf-harness-brain-core\sf-harness.code-workspace
```

VS Code opens and asks whether you trust the workspace. Review the folder, then choose **Trust**
(the Copilot customizations do not load in Restricted Mode). When VS Code offers the
workspace-recommended extensions, install them.

> From here on, the guided script can do Parts 3–8 for you: open the VS Code terminal
> (`` Ctrl+` ``) and run `python scripts\first_launch.py`. It is plain Python — no PowerShell
> execution policy involved. To continue manually, keep going.

---

## Part 3 — Python environment

In the VS Code terminal (`` Ctrl+` ``), from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r requirements-dev.lock
```

Success ends with `Successfully installed jsonschema... PyYAML...`. The `--require-hashes` flag
verifies every downloaded package against the pinned checksums — do not replace this command
with a plain `pip install`.

**Now select the interpreter (required, easy to miss):** Command Palette (`Ctrl+Shift+P`) →
**Python: Select Interpreter** → pick the entry ending in `.venv\Scripts\python.exe`. Without
this, harness scripts later fail with `ModuleNotFoundError: No module named 'jsonschema'`.

macOS/Linux: `python3 -m venv .venv`, then use `.venv/bin/python` in place of
`.\.venv\Scripts\python.exe` throughout.

## Part 4 — Node dependencies

```powershell
npm ci --ignore-scripts
```

Success prints `added NNN packages`. Use exactly `npm ci --ignore-scripts` — not `npm install`
(which can rewrite the lockfile) and not without `--ignore-scripts` (which would run arbitrary
package install scripts).

`npm audit` will report ~24 known advisories afterwards. **This is expected and formally
accepted** — they are transitive to Salesforce's own pinned tooling and not fixable on stable
channels today; see `SECURITY.md` and the 2026-07-13 entry in `.ai/memory/decisions-log.md`.
Do not run `npm audit fix --force`.

## Part 5 — First verification checkpoint

```powershell
.\.venv\Scripts\python.exe scripts\validate_harness.py
```

Expected: `PASS`. If this fails, your clone or install is
incomplete — fix that before continuing.

At this stage `config/harness.local.json` still contains `<PLACEHOLDER>` values (or does not
exist yet). That is correct — workflows that need those values fail closed until Part 6 is
done; `first_launch.py` lists every unresolved placeholder by path.

---

## Part 6 — Local configuration

Create your machine-local config from the tracked example:

```powershell
Copy-Item config\harness.example.json config\harness.local.json
```

This file is **gitignored**: it never leaves your machine and is never committed. Open it in
VS Code and replace the `<PLACEHOLDER>` values. You cannot invent these — get them from your
team lead / harness maintainer:

| Field | What it is | Where it comes from |
|---|---|---|
| `ado.organization` | Azure DevOps organization slug (e.g. `contoso`, not a URL) | team lead |
| `ado.project` | ADO project name | team lead |
| `ado.releaseQueryId` | Saved ADO query id for release scope (only release flows need it) | team lead |
| `salesforce.orgs[].alias` | Your local alias for each sandbox (you choose it; reuse it in Part 7) | you |
| `salesforce.orgs[].expectedInstanceHost` | The org's My Domain host (optional pin; set together with the org id) | filled in Part 7 |
| `salesforce.orgs[].expectedOrganizationId` | The org id (optional pin; set together with the host) | filled in Part 7 |
| `salesforce.review.allowedObjectApiNames` | Objects the agent may read via the review facade | team lead (keep narrow) |

There is no write-mode Salesforce MCP. The review facade remains read-only, while the Developer
uses direct `sf`/`sfdx` commands for in-scope org changes. Every real deployment requires fresh
chat confirmation for its exact target and scope; data mutations do not use that deploy-specific
gate.

## Part 7 — Set `ADO_ORGANIZATION` and authorize a sandbox

### 7.1 The environment variable (the #1 setup pitfall)

The ADO MCP server URL is built from an **environment variable**, and the safety hook requires
it to exactly equal `ado.organization` in your config. Set it persistently:

```powershell
setx ADO_ORGANIZATION "your-org-slug"
```

Then **fully quit VS Code** (all windows — check no `Code.exe` remains in Task Manager) and
reopen it. "Reload Window" is NOT enough; environment variables are read at process launch.
Verify in a new terminal: `echo $env:ADO_ORGANIZATION` prints your slug.

macOS/Linux: `export ADO_ORGANIZATION="your-org-slug"` in your shell profile, then launch VS
Code from that shell.

### 7.2 Authorize the sandbox

Ask your team lead which sandbox to use and its login URL. Then (alias must match Part 6):

```powershell
sf org login web --instance-url https://test.salesforce.com --alias my_review_sbx
```

A browser opens; sign in with **your own** sandbox user. Never paste credentials into a
terminal, a file, or Copilot chat. Then read the authorized org configuration:

```powershell
sf org display --target-org my_review_sbx --json
```

From the JSON `result`, copy the host part of `instanceUrl` (looks like
`mydomain--sbxname.sandbox.my.salesforce.com`) into `expectedInstanceHost` and `id` into
`expectedOrganizationId` in `config\harness.local.json`. Only non-production orgs are accepted:
the host must carry a sandbox (`*--*.sandbox.my.salesforce.com`), scratch-org, or Developer
Edition (`*.develop.my.salesforce.com`) signature. Production host shapes are refused by design;
the facade performs no separate Organization identity query. No toggle is
needed for any non-production shape (owner decision 2026-08-04); the pins are optional — an
unlisted alias is also readable, but only configured entries can anchor Knowledge org snapshots.

## Part 8 — Final verification

```powershell
.\.venv\Scripts\python.exe scripts\validate_harness.py                            # structure
.\.venv\Scripts\python.exe -m unittest discover -s tests                          # optional, ~20s
```

Both should PASS now. There is no separate readiness command: Salesforce MCP checks the configured
host/org-id walls in the background and logs every CLI stage in MCP Output; ADO scope is checked on every
tool call. If an ADO call fails on the organization not matching local policy, re-check
Part 7.1 (exact slug, no trailing spaces, VS Code fully restarted). To diagnose one org by
hand: `.\.venv\Scripts\python.exe scripts\verify_salesforce_org.py --org <alias>`.

## Part 9 — First Copilot prompt

1. VS Code may prompt *"The MCP servers … Start them now?"* — start **`salesforce`**
   and **`ado-readonly`** (the only configured servers; both are read-only).
2. When prompted for the `sf_review_org` input, enter your sandbox alias (e.g. `my_review_sbx`).
3. Reduce approval clicks: Command Palette → **Chat: Manage Tool Approval** → trust all tools
   under `salesforce` and `ado-readonly` at **workspace** scope. Never enable global
   auto-approve (`/yolo`).
4. Open Copilot Chat and run your first command:

   ```text
   /fetch-ado-item itemId=12345
   ```

   (any real work-item id from your ADO project). The agent should persist the requirement
   snapshot to `work-items/12345-<slug>/ado-context.md`, report it, and stop with the next
   command — without ever showing raw CLI commands or credentials.
5. Sanity-check the rails with a negative test: ask the agent to query production. It must be
   denied.

**Where to go next:** `README.md` for the architecture, `SETUP.md` §5–7 for the full operating
model (work items, approvals, knowledge), and the eighteen `/` prompt commands in Copilot Chat.

## When something fails

Read `.cache\denials.log` first — every hook denial is appended there as one JSON line with the
reason:

```powershell
Get-Content .cache\denials.log -Tail 20
```

Then use the symptom table in [windows-setup.md](windows-setup.md#troubleshooting--the-exact-errors-and-their-fixes).
The three most common failures are: `ADO_ORGANIZATION` not set / VS Code not fully restarted
(Part 7.1), the `.venv` interpreter not selected (Part 3), and placeholders still present in
`config\harness.local.json` (Part 6).
