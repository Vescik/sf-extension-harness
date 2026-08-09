# Open problems — znane, świadomie odłożone

Data założenia: 2026-08-09. Rejestr problemów znanych i **celowo** nienaprawionych,
każdy z kryterium eskalacji, po którym przestaje być „odłożony" i staje się robotą.
Zasada wpisu: co się dzieje, dlaczego odłożone, po czym poznać, że czas naprawić,
i jaka jest znana naprawa. Wpisy usuwa się po naprawie (z commitem, który naprawił)
albo po unieważnieniu (z powodem).

---

## OP-1 — Windows: timeout subprocess nie zabija drzewa procesów (W-2, audyt 2026-08-09)

**Co**: `subprocess.run(timeout=…)` po `TimeoutExpired` woła `TerminateProcess`
wyłącznie na bezpośrednim dziecku. Na ścieżce fallbacku spawnu CLI
(`sf.cmd` → cmd.exe → node) timeout osieroci proces node; na ścieżce preferowanej
(`node bin\run.js`) dzieckiem jest sam CLI i ryzyko jest znikome.

**Czemu odłożone**: ekspozycja ogranicza się do 3–4 wywołań CLI na start/refresh
sesji (nie per call), timeouty są długie (60 s / 15 s), a sierota to pojedynczy
bezczynny proces, nie wyciek w pętli. Prewencyjna implementacja `taskkill /T` to
mechanizm bez zaobserwowanej potrzeby (content over process).

**Kryterium eskalacji — naprawiamy, gdy zajdzie KTÓREKOLWIEK**:
1. Ktokolwiek zaobserwuje na maszynie zespołu osierocony proces `node`/`sf` po
   timeout'cie startu fasady (Task Manager / `tasklist | findstr node` po
   komunikacie `CLI_UNAVAILABLE`/`CLI_TIMEOUT` na stderr serwera) — **jeden
   potwierdzony przypadek wystarcza**;
2. fallback `sf.cmd` stanie się ścieżką główną (np. existence-check `run.js`
   zacznie regularnie zawodzić po zmianie layoutu paczki CLI — widoczne jako
   `sf resolution: path=...sf.cmd batch=True` na stderr zamiast `node bypass`);
3. do fasady dojdzie jakikolwiek spawn CLI per call (dziś nie ma żadnego).

**Znana naprawa** (~30 linii + test): przy spawnie celu `.cmd` na win32 użyć
`creationflags=CREATE_NEW_PROCESS_GROUP`, a po `TimeoutExpired` dobić drzewo
`taskkill /T /F /PID <pid>`; alternatywnie zawsze wymuszać ścieżkę `run.js` i
traktować brak `run.js` jako loud-fail zamiast fallbacku.

**Właściciel**: fasada (`scripts/salesforce_review_server.py`, `run_cli_json`).

---

## OP-2 — Windows: komenda hooka przybita jako `python3` vs standard `python` (W-4, audyt 2026-08-09)

**Co**: `.github/hooks/safety.json` i pin w `validate_harness.py` wymuszają
`python3 scripts/copilot_safety_hook.py`, podczas gdy `docs/windows-setup.md`
standaryzuje na Windows `python` (instalator python.org nie tworzy `python3.exe`).
Jeśli na maszynie zespołu `python3` nie istnieje, hook może się cicho nie
odpalać — a cichy brak hooka bezpieczeństwa jest gorszy niż jego brak jawny.

**Czemu otwarte, nie naprawione w ciemno**: harness działał już na maszynach
zespołu, więc coś tę komendę rozwiązuje (alias MS Store? PATH-owy shim? sposób,
w jaki Copilot uruchamia hooki). Zmiana pinu bez zrozumienia, czemu działa,
mogłaby zepsuć działającą konfigurację.

**Kryterium rozstrzygnięcia (do wykonania przy najbliższej okazji na maszynie
zespołu, ≤5 minut)**: w terminalu VS Code uruchomić `python3 --version` ORAZ
sprawdzić w logu Copilota, że PreToolUse hook faktycznie odpalił się przy
dowolnej komendzie terminalowej (widoczna odmowa dla `rd /s /q .` w pustym
katalogu testowym jest jednoznacznym dowodem). Wynik zapisać tutaj.
**Eskalacja natychmiastowa**, jeśli hook się nie odpala: zmiana komendy na
`python` + aktualizacja pinu walidatora w jednym commicie.

**Właściciel**: `.github/hooks/safety.json` + `scripts/validate_harness.py:732`.
