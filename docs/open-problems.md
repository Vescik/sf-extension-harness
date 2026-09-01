# Open problems — znane, świadomie odłożone

Data założenia: 2026-08-09. Rejestr problemów znanych i **celowo** nienaprawionych,
każdy z kryterium eskalacji, po którym przestaje być „odłożony" i staje się robotą.
Zasada wpisu: co się dzieje, dlaczego odłożone, po czym poznać, że czas naprawić,
i jaka jest znana naprawa. Wpisy usuwa się po naprawie (z commitem, który naprawił)
albo po unieważnieniu (z powodem).

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
