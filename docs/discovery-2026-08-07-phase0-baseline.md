# Discovery — Faza 0: baseline snapshotu przed przebudową context-first

Data: 2026-08-07
Plan nadrzędny: `plan-2026-08-07-context-first-architecture.md` (+ `plan-2026-08-07-lightweight-additions.md`)
Zakres: inwentaryzacja stanu repo po snapshocie (commit `52348b0`, jedyny commit) względem
struktury docelowej §2 planu; imienna lista do zamrożenia (faza 5); warunki pomiaru §7.

## 1. Bramka bazowa — zielona (zmierzone, nie założone)

| Krok | Wynik |
|---|---|
| `scripts/validate_harness.py` | **PASS, 2716 checks** — „6 agents, 18 prompts, 18 internal skills, 3 scoped instruction files" |
| `python -m unittest discover -s tests` | **986 testów, OK** (skipped=2) — po instalacji zależności; bez `npm ci` padają 3 testy `test_salesforce_review.PinnedSalesforceMcpCompatibilityTests` (brak `node_modules/@salesforce/mcp`), to brak środowiska, nie defekt |
| `scripts/run_evals.py` | **PASS, 37 deterministic safety evaluations** |

Środowisko postawione lokalnie (oba gitignored): `.venv/` z `requirements-dev.lock`,
`node_modules/` z `npm ci`. Testy generują `config/harness.local.json` (gitignored).
Żaden plik trackowany nie został zmieniony podczas inwentaryzacji.

## 2. Stan vs struktura docelowa (§2 planu)

### `.github/` — istnieje w starej formie, do przebudowy (fazy 1 i 3)

- `copilot-instructions.md` — jest; stara forma, do napisania od nowa (~40 linii orientacji).
- `instructions/` — 3 pliki: `managed-package-constraints`, `organization-principles`,
  `salesforce-best-practices` → do rozbicia na `managed-package` (`**`) / `apex`
  (`**/*.cls`) / `flows` (`**/*.flow-meta.xml`).
- `agents/` — 6 starych: `config-investigator`, `development-assistant`,
  `guardrail-reviewer`, `knowledge-curator`, `solution-designer`, `test-strategist`
  → docelowo `designer`/`developer`/`reviewer` + `git-agent` (L-6).
- `prompts/` — 18; `skills/` — 18. Z tego zostają na pewno: komplet handover (§3.12/C-4)
  i przydatne jako baza przepisów: `solution-design`, `investigate-object`,
  `investigate-config-records` (→ `org-discovery`), `check-against-principles`
  (→ procedura reviewer-agenta).
- `pull_request_template.md` — **już istnieje** → L-2 to edycja, nie nowy plik.
- `hooks/safety.json`, `workflows/harness-ci.yml`, `mcp.json` (tylko serwer `knowledge`),
  `CODEOWNERS`, `dependabot.yml` — obecne.
- „Do not announce phases" — **już usunięte wcześniej** (ślad: `.ai/memory/decisions-log.md`
  ~linia 1107); grep po `.github/`, `AGENTS.md`, `README.md`, `SETUP.md` daje zero trafień.
  Punkt fazy 1 = sama weryfikacja, zrobiona.

### `docs/` — warstwa docelowa NIE istnieje (faza 2 tworzy od zera)

Brak `package-concept.md`, `package-constraints.md`, `design-guides.md`,
`keywords-taxonomy.md`, `areas/`. Zalążek taksonomii istnieje w innym miejscu:
`.ai/knowledge/keyword-taxonomy.md` — do wykorzystania jako materiał wejściowy §3.6
(bez ruszania `.ai/knowledge`). Obecne `docs/` to ~23 dokumenty historyczne
(knowledge-*, discovery-*, evidence-*) — nie kolidują nazwami z warstwą docelową.

### `work-items/` — nie istnieje (faza 3 tworzy; L-4 README od razu)

### `.ai/` — zostaje; store wiedzy niemal pusty

`knowledge/`: tylko `features/`, `keyword-taxonomy.md`, `README.md` — kontrakt i narzędzia
są, treści mało (spójne z ryzykiem pojemności approvera odroczonym w §3.7).
`templates/`: `release-handover.md` (zostaje — C-4), `feature-health-report.md`,
`technical-documentation.md` (los razem z ich promptami — rozstrzygnąć w fazie 3).
`contracts/`: `execution-contract.md`, `solution-design-runtime.md`,
`workflow-state-machine.md`, `source-authority.md`, `tool-capabilities.md` —
SD-owe z tej listy to kandydaci do zamrożenia/oznaczenia stale w fazie 5.

## 3. Imienna lista do zamrożenia (wejście fazy 5)

Skrypty (zamrożenie całych plików — brak konsumentów poza światem SD, zweryfikowane grepem
importów):
- `scripts/solution_design.py`, `solution_design_core.py`, `solution_design_worker.py`,
  `solution_design_mcp_server.mjs`
- `scripts/ado_requirement_adapter.mjs` — jedyny konsument: `solution_design_mcp_server.mjs`
- `scripts/governed_state.py` — konsumenci: SD worker + `repository_evidence_adapter.py`
- `scripts/repository_evidence_adapter.py`, `scripts/sampling_derivers.py` — grep nie
  znalazł żadnych konsumentów; potwierdzić jeszcze raz w fazie 5 przed oznaczeniem

**NIE zamrażać w całości** (importowane przez warstwy, które zostają):
- `work_record.py` — importują go `copilot_role_guard`, `knowledge_store`, `schema_format`,
  `validate_harness`; zamrożeniu podlega wyłącznie lane SD wewnątrz modułu
- `preflight.py` — importują `copilot_role_guard`, `first_launch`, `validate_harness`,
  `salesforce_review_server.mjs`

Schematy: `solution-design-state.schema.json` na pewno; klasyfikacja pozostałych
procesowych (`work-evidence`, `verification-receipt`, `verification-policy`,
`dependency-admission`, `handoff-envelope`, `change-record`) — w fazie 5, po ustaleniu,
czego dokładnie używa pozostający kod (część konsumuje work_record/knowledge).

Testy sprzężone: `test_solution_design_loop.py` (cały), części `test_work_record.py`
i `test_receipt_gates.py` — do przejrzenia w fazie 5 razem z pinami.

Rejestracje: `.vscode/mcp.json` zawiera serwer `solution-design`
(`solution_design_mcp_server.mjs`) — zamrożenie oznacza wyrejestrowanie z mcp.json
(plik zostaje na dysku); `.github/mcp.json` ma tylko `knowledge`, bez zmian.

## 4. Fakty istotne dla dalszych faz

- **Piny** (`validate_harness.py:52`): `EXPECTED_COUNTS = {"agents": 6, "prompts": 18,
  "skills": 18, "instructions": 3}`; dodatkowo: liczba public slash commands ==
  liczba promptów, rejestr `EXPECTED_HUMAN_PLACEHOLDERS`, `AGENTS.md` ≤150 słów jako
  compatibility shim, walidator pinuje wprost skill `generate-release-handover` (linia
  ~1034 — spójne z C-4). Fazy 1/3 bez fazy 6 wywalą bramkę — kolejność faz jest twarda.
- **Safety hook bez wzorca force-push** (potwierdzone grepem `copilot_safety_hook.py`):
  linia `push --force*`/`push -f` z L-6 §7.2 jest faktycznie do dodania; `rm -rf`
  i produkcyjne hosty są pokryte.
- **Handover feature — komplet obecny** (C-4): prompt, skill, `.ai/templates/release-handover.md`,
  `scripts/validate_handover_output.py`, `tests/test_validate_handover_output.py`,
  fixtura `evals/fixtures/output.release-handover.valid.json`, krok CI, scenariusz
  `release-scope-incomplete` w `evals/agent-scenarios.yaml`, katalog `output/handover/`.
- MCP dla VS Code (`.vscode/mcp.json`): `ado-readonly`, `salesforce-readonly` (fasada
  `start_salesforce_mcp.mjs --mode review`), `knowledge`, `solution-design` (do
  wyrejestrowania w fazie 5).
- CI (`harness-ci.yml`): validate → unittest → run_evals → prettier/lint → check-ignore;
  przegląd w fazie 6 pod kroki, które znikną.

## 5. Warunki pomiaru §7 (baseline „czysty Copilot")

`docs/` warstwy docelowej jeszcze nie ma, więc przebieg „czysty Copilot" można wykonać
w dowolnym momencie **przed** fazą 2 — albo po niej, na snapshocie sprzed fazy 2
(commit graniczny będzie punktem odcięcia). Do zapisania przy przebiegu: model i wersja
hosta, ticket, liczba zmyślonych obiektów/relacji, trafione constraints, rundy
doprecyzowań. Ten sam ticket posłuży potem przebiegowi „Copilot z docs".

## 6. Wnioski dla kolejności

Faza 0 nie ujawniła blokerów. Jedna korekta praktyczna: fazy 1 i 3 zmieniają liczności
pinowane przez `validate_harness.py`, więc bramka będzie czerwona między fazą 1 a 6 —
albo piny aktualizuje się przyrostowo przy każdej fazie (rekomendowane: commit per faza
z lokalnie zieloną bramką), albo akceptuje się czerwień do fazy 6. Rekomendacja:
przyrostowo — zgodnie z krokiem 7 procedury naprawy z workspace'u buildera.
