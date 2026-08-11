# Plan fazy 1 — `approved-drifted` jako skuteczne approved

Data: 2026-08-11  
Status: **plan do realizacji; bez implementacji w tym dokumencie**  
Priorytet: agent productivity first  
Repozytorium: `sf-extension-harness` (ten repozytorium)  
Stan odniesienia po finalnej weryfikacji planu: `main@cb0dd80`; `origin/main@5caec99`

## Instrukcja dla `/goal`

Przekaż agentowi następujący cel razem z tym plikiem:

> Zrealizuj dokładnie fazę 1 opisaną w
> `docs/plan-2026-08-11-approved-drifted-phase-1.md`. Najpierw wykonaj preflight i
> zinwentaryzuj istniejące zmiany. Nie nadpisuj cudzej pracy, nie rozszerzaj zakresu o fazy 2–4,
> nie zmieniaj schematów Entry ani output-envelope i nie wprowadzaj nowych lifecycle lanes.
> Kontynuuj aż wszystkie kryteria akceptacji i bramy końcowe będą spełnione albo wystąpi nazwany
> w planie warunek STOP. W raporcie końcowym podaj commity, pliki, wyniki testów i każde świadome
> odstępstwo.

Plan jest samowystarczalny. Agent nie ma ponownie otwierać decyzji opisanych w sekcji 3.

---

## 1. Cel i oczekiwany rezultat

Faza 1 ma usunąć sprzeczność pomiędzy istniejącą decyzją ownera a zachowaniem runtime'u:

- owner zdecydował, że source drift jest ujawnieniem, a nie unieważnieniem approval;
- `author-feature` i resolver Feature binding już przyjmują `approved-drifted`;
- `entry-verify-citations` zwraca dla niego warning zamiast invalid;
- ale retrieval domyślnie zwraca tylko `approved-current`, umieszcza drifted w non-current
  buckets i instruuje agentów, żeby nie cytowali go jako effective.

Po fazie 1:

1. `approved-current` i `approved-drifted` są dwiema skutecznymi odmianami zatwierdzonego Entry.
2. Obie są domyślnie wyszukiwane, cytowalne, liczone do coverage i mogą wspierać `SAFE`.
3. `approved-drifted` zawsze niesie krótkie, widoczne advisory `SOURCE_DRIFT`, ale advisory samo
   nie zmienia werdyktu i nie wymusza reapproval.
4. Brak albo nieczytelność zatwierdzonego source fragmentu nie jest zwykłym drift — Entry przechodzi
   do `not-effective` z jednoznacznym kodem problemu.
5. Release-cycle report pokazuje jedną zbiorczą kolejkę maintenance. Sam wiek Entry nigdy nie
   wygasza approval i nigdy nie powoduje pytań per Entry.
6. Reguły retrieval mają jedno źródło w `search-knowledge/SKILL.md`; konsumenci zawierają tylko
   obowiązek właściwy dla swojego outputu oraz minimalne tokeny wymagane przez Set A.
7. Prompt `check-against-principles` nie nadpisuje przypadkowo narzędzi reviewera; reviewer ma
   dokładnie te read-only narzędzia, których wymaga jego skill.

## 2. Stan początkowy, którego nie wolno zgubić

Podczas finalnej weryfikacji planu istnieją trzy lokalne commity ponad `origin/main`:

- `02e2882` — uproszczenie `check-against-principles` i one-source procedure;
- `f16cd81` — prose alignment: `approved-drifted` effective with disclosure.
- `cb0dd80` — `decisions.md` jako log, uzupełniony reviewer SOQL contract i jawny missing
  verification plan.

Pięć plików, które podczas początkowego discovery było zmodyfikowanych lokalnie, weszło następnie
do `cb0dd80`:

- `.ai/contracts/execution-contract.md`;
- `.ai/contracts/tool-capabilities.md`;
- `.ai/repo-map.json`;
- `.ai/templates/technical-documentation.md`;
- `.github/skills/generate-technical-documentation/SKILL.md`.

Agent ma traktować powyższe commity jako cudzą, zakończoną pracę. Przed pierwszą edycją musi
ponownie odczytać `git status --short`, `git log --oneline --decorate -12` i pełny diff. Stan może
zmienić się po utworzeniu planu; aktualny Git jest źródłem prawdy.

Nie należy ponownie implementować elementów już obecnych w `f16cd81`:

- generic-bucket ma kanoniczny opis w `search-knowledge`;
- `check-against-principles` ma jawną enumerację stanów;
- `entry-verify-citations --envelope` wróciło do kroku 7;
- `check-feature-coverage` prose uznaje drifted za approved.

Te elementy należy dostosować do finalnego runtime'u, a nie usuwać i pisać od nowa.

## 3. Zamrożone decyzje ownera

### D1 — approval i freshness są osobnymi osiami

`approved-drifted` pozostaje approved. Source drift nie cofa ludzkiego approval, ponieważ
`reviewedContentDigest` wiąże zatwierdzone facts/semantics, a nie późniejszą niezmienność source
bytes.

### D2 — drift jest advisory, nie blockerem

Sama flaga `SOURCE_DRIFT`:

- nie blokuje `SAFE`;
- nie obniża coverage;
- nie wyklucza z main approved buckets;
- nie wymusza reapproval;
- nie tworzy maintenance taska;
- nie zmienia `effective: true` ani ważności cytowania.

Jeżeli aktualne repo/org evidence konkretnie przeczy zatwierdzonemu faktowi, blokuje rzeczywista
sprzeczność, nie flaga drift.

### D3 — brak źródła nie jest driftem

Brakujący lub nieczytelny source fragment oznacza integrity/evidence failure:

- lane: `not-effective`;
- `effective: false`;
- machine-readable problem code;
- brak cytowania jako skuteczne Knowledge;
- pozycja w release-cycle `requiresDecision`.

Nie dodawać nowego lifecycle lane `source-missing`.

### D4 — czas nie wygasza approval

Domyślny release cycle ma 30 dni, ale wiek jest wyłącznie parametrem raportu maintenance.
`approved-current` starsze niż 30 dni pozostaje bez akcji. Drifted starsze niż cykl trafia do
opcjonalnej kolejki refresh; nadal jest effective.

### D5 — żadnych automatycznych zapisów w fazie 1

Faza 1 nie aktualizuje source pinów, Entry ani ledgerów. Maintenance report jest read-only.
Automatic source-pin refresh należy do przyszłej fazy po danych z pilota.

### D6 — jedno źródło procedury

Lane handling, citations, freshness/hydration i generic-bucket żyją w
`.github/skills/search-knowledge/SKILL.md`. Inne skille wskazują na ten dokument. Wyjątek Set A:
każda powierzchnia nadal musi zawierać literalne `knowledge_context` i `hydrated`, ponieważ
`validate_harness.py` mechanicznie pinuje oba tokeny.

### D7 — reviewer agent jest źródłem tool permissions

`.github/prompts/check-against-principles.prompt.md` nie deklaruje własnego `tools:`. Dziedziczy
narzędzia z `.github/agents/reviewer.agent.md`. Reviewer dostaje read-only `search` i
`execute/runInTerminal`, ponieważ skill musi znaleźć kod i uruchomić guarded
`entry-verify-citations`. Nie dodawać ADO wildcard ani narzędzi zapisu.

## 4. Tabela semantyki docelowej

| Lane / problem                     |             `effective` | Citable |       Main approved buckets | Coverage / `SAFE` | Obowiązkowa informacja                                     |
| ---------------------------------- | ----------------------: | ------: | --------------------------: | ----------------: | ---------------------------------------------------------- |
| `approved-current`                 |                    true |     tak |                         tak |               tak | brak                                                       |
| `approved-drifted`                 |                    true |     tak |                         tak |               tak | `SOURCE_DRIFT` + zmienione ścieżki                         |
| `draft`                            |                   false |     nie |                         nie |               nie | draft                                                      |
| `revoked`                          |                   false |     nie |                         nie |               nie | revoked                                                    |
| `not-effective`                    |                   false |     nie |                         nie |               nie | reason/problem codes                                       |
| `scope-mismatch`                   |                   false |     nie |                         nie |               nie | scope mismatch                                             |
| `unsupported-profile`              |                   false |     nie |                         nie |               nie | unsupported profile                                        |
| source fragment missing/unreadable |                   false |     nie |                         nie |               nie | `SOURCE_FRAGMENT_MISSING` lub `SOURCE_FRAGMENT_UNREADABLE` |
| `hydrated: false`                  | false dla danego wyniku |     nie | nie jako zweryfikowany fakt |               nie | hydration/integrity gap                                    |

Org-usage pozostaje osobną osią. `org-expired` oznacza brak aktualnych liczb org usage, ale nie
zmienia approval repository-source Entry.

## 5. Zakres fazy 1

### W zakresie

- core lane/effectiveness helpers;
- rozróżnienie changed, missing i unreadable source fragments;
- citation verification;
- default retrieval i wszystkie buckety search/explain/impact/context;
- teksty MCP i capabilities;
- kompaktowe advisory i usunięcie obowiązku rebuild/reapproval wywołanego samym driftem;
- read-only release-cycle summary przez `entry-coverage`;
- `search-knowledge` jako kanoniczne źródło reguł;
- cztery konsumujące skille i `curate-knowledge`;
- `check-against-principles` tool reachability;
- kontrakt Knowledge, README, decisions log, repo map;
- unit tests, contract tests, safety tests, eval scenarios i pełne bramy repo.

### Poza zakresem

- semantic re-extraction i porównanie nowego `factsDigest`;
- task-aware materiality;
- live freshness overlay dla wszystkich zwracanych rows;
- automatyczny source-pin refresh;
- zapisy do Entry lub ledgerów;
- nowy scheduler/automation;
- nowe lifecycle lanes;
- zmiany `schemas/knowledge-entry.schema.json`;
- zmiany `schemas/output-envelope.schema.json`;
- cleanup historycznego `recordRef`/handoff;
- przebudowa Feature Knowledge;
- expiry approval po czasie;
- globalny refresh wave;
- zmiany w Salesforce/ADO runtime.

Jeżeli realizacja wymaga elementu z tej listy, agent ma zatrzymać się zgodnie z sekcją 12, zamiast
rozszerzać scope.

## 6. Szczegółowa kolejność implementacji

### Krok 0 — preflight i baseline

1. Przeczytaj w całości `AGENTS.md`, `.github/copilot-instructions.md` i relewantne sekcje
   `.ai/repo-map.md`.
2. Zapisz w raporcie roboczym:
   - aktualny branch i HEAD;
   - relację do `origin/main`;
   - wszystkie tracked/untracked changes;
   - pliki pokrywające się z zakresem planu.
3. Przeczytaj aktualny diff każdego pokrywającego się pliku. Edytuj addytywnie; nie przywracaj
   wersji z HEAD nad cudzą zmianą.
4. Uruchom baseline:

   ```bash
   .venv/bin/python scripts/validate_harness.py
   .venv/bin/python -m unittest \
     tests.test_knowledge_store \
     tests.test_knowledge_search \
     tests.test_knowledge_contract \
     tests.test_feature_knowledge \
     tests.test_knowledge_mcp_contract \
     tests.test_safety_hooks
   .venv/bin/python scripts/run_evals.py
   ```

5. Jeżeli baseline nie jest zielony, sklasyfikuj failure jako istniejący albo związany z aktualnym
   local diff. Nie maskuj go zmianą semantyki fazy 1.

### Krok 1 — jedna definicja skutecznego approved

Plik główny: `scripts/knowledge_store.py`.

1. Wprowadź jedną stałą/helper będący źródłem prawdy, np.:

   ```python
   EFFECTIVE_ENTRY_LANES = frozenset({"approved-current", "approved-drifted"})

   def is_effective_entry_lane(lane: str | None) -> bool:
       return lane in EFFECTIVE_ENTRY_LANES
   ```

2. `scripts/knowledge_search.py` ma importować/używać tego źródła zamiast definiować inną semantykę
   skuteczności.
3. Nie zmieniaj nazw istniejących lanes ani ich reprezentacji w Entry schema.
4. Każdy receipt z `compute_lane` ma jednoznacznie podawać:
   - `effective: true|false`;
   - dla approved: `freshness: current|drifted`;
   - dla innych lanes: `freshness: unknown` albo brak, konsekwentnie w całym API;
   - `advisories: []` lub listę machine-readable advisories.
5. Zachowaj istniejące `lane`, digests, path i problems dla kompatybilności.

Docelowe minimalne receipts:

```json
{
  "lane": "approved-current",
  "effective": true,
  "freshness": "current",
  "advisories": []
}
```

```json
{
  "lane": "approved-drifted",
  "effective": true,
  "freshness": "drifted",
  "advisories": [
    {
      "code": "SOURCE_DRIFT",
      "paths": ["force-app/main/default/flows/Example.flow-meta.xml"]
    }
  ]
}
```

### Krok 2 — source freshness bez nowego lane

Plik główny: `scripts/knowledge_store.py`.

1. Zastąp boolean-only `regenerate_fragment_digest` helperem zwracającym wynik strukturalny.
2. Helper ma rozróżniać:
   - wszystkie digests zgodne: `current`;
   - plik istnieje i digest się różni: `drifted`;
   - plik nie istnieje: `missing`;
   - pliku nie można odczytać: `unreadable`.
3. Wynik ma zawierać konkretne ścieżki. Nie zwracaj samego boolean.
4. `compute_lane` mapuje:
   - `current` → `approved-current`, effective true;
   - `drifted` → `approved-drifted`, effective true, advisory;
   - `missing` → `not-effective`, effective false, problem code
     `SOURCE_FRAGMENT_MISSING` i lista ścieżek;
   - `unreadable` → `not-effective`, effective false, problem code
     `SOURCE_FRAGMENT_UNREADABLE` i lista ścieżek.
5. Nie przepisuj Entry, source digestu ani ledger recordu.
6. Nie uruchamiaj collectorów i nie porównuj facts — to faza 2/3.

Problem codes powinny być osobnym polem, np. `problemCodes`, a tekstowe `problems` pozostają dla
człowieka. Nie parsuj semantyki z tekstu problemu w downstream.

### Krok 3 — citation verification jako valid-with-advisory

Plik główny: `scripts/knowledge_store.py`.

1. Dla `approved-current` zachowaj valid/ok.
2. Dla `approved-drifted`:
   - zachowaj rozpoznawalny `verdict: drifted` dla kompatybilności;
   - ustaw `severity: ok`, nie `warning` ani `invalid`;
   - dodaj `effective: true`;
   - dodaj advisory code `SOURCE_DRIFT` i ścieżki;
   - usuń tekst „re-approve before citing as current”;
   - reason ma jasno mówić: approved, effective, citable, disclose drift.
3. Dla missing/revoked/draft/not-effective/digest mismatch zachowaj `invalid` i dodaj
   `effective: false`.
4. `entry-verify-citations` zachowuje istniejące liczniki `ok`, `warning`, `invalid`, aby nie łamać
   konsumentów. Drifted liczy się do `ok`. Dodaj addytywny licznik `advisory`, jeśli nie wymaga to
   zmiany schematu; nie usuwaj starych kluczy.
5. Envelope zawierający wyłącznie current i drifted refs ma `invalid: 0` i może wspierać `SAFE`.

### Krok 4 — domyślne retrieval obejmuje oba approved lanes

Plik główny: `scripts/knowledge_search.py`.

1. Zmień `ESTABLISHED_STATES` na oba skuteczne lanes:

   ```python
   ESTABLISHED_STATES = ("approved-current", "approved-drifted")
   ```

2. Zastąp `lane_split` semantyką effective/non-effective. Nazwa helpera powinna odzwierciedlać
   zachowanie, np. `effectiveness_split`.
3. Main buckets zawierają current i drifted:
   - `approvedResults`;
   - `parts`;
   - `permissions`;
   - `incoming`;
   - `chains`;
   - analogiczne effective rows w `explain` i `impact`.
4. `nonCurrentResults` i `*NonCurrent` pozostają dla kompatybilności, ale nie mogą zawierać
   `approved-drifted`. Zawierają tylko rzeczywiście non-effective/opted-in lanes i unresolved rows
   zgodnie z obecnym kontraktem.
5. Każdy drifted row nadal ma własne `lifecycle: approved-drifted`, `effective: true` oraz advisory.
6. Capping pozostaje osobny dla effective i non-effective buckets; drifted nie może konsumować
   budżetu non-effective ani wypychać draft/revoked inspection rows.
7. Explicit `--state` nadal działa. Opis CLI/MCP ma uczciwie wyjaśniać, że przekazanie `--state`
   zastępuje domyślny filtr, jeżeli tak działa parser; nie nazywaj override „dodaniem lane”, jeśli
   runtime naprawdę zastępuje listę.
8. `capabilities.defaultStates` ma zwracać oba approved lanes.

### Krok 5 — anchor advisory i kompaktowe komunikaty

Pliki: `scripts/knowledge_search.py`, powiązane testy.

1. `source_drift_gaps`/jego następca ma odróżniać changed od missing/unreadable.
2. Zmiana digestu na anchorze:
   - emituje jeden advisory z identity i listą ścieżek;
   - nie mówi „do not cite”;
   - nie mówi „rebuild before citing”;
   - nie wymusza ponownego discovery.
3. Missing/unreadable source:
   - emituje integrity gap;
   - wymaga live `knowledge_entry_status`/`entry-status` przed cytowaniem;
   - nie jest przedstawiane jako zwykły drift.
4. `ROW_LIFECYCLE_DISCLOSURE` ma być krótkie i pojedyncze. Docelowy sens:

   > Row lifecycle labels are index-fresh; obtain a store-fresh entry-status receipt before
   > citation. Approved-drifted remains effective with SOURCE_DRIFT disclosure.

5. Usuń powtarzające się komunikaty „not approved-current knowledge” dla drifted. Nie usuwaj
   ostrzeżeń dla draft/revoked/not-effective/unresolved/hydration failures.
6. Nie implementuj live source overlay dla wszystkich rows. W fazie 1 store-fresh citation receipt
   pozostaje finalną bramą.

### Krok 6 — MCP descriptions i contract surface

Plik: `scripts/knowledge_mcp_server.mjs`.

1. `STATE_PROP` nadal wymienia wszystkie lanes.
2. Opis domyślnego zachowania wskazuje, że current i drifted są effective approved.
3. `*NonCurrent` jest opisane jako miejsce non-effective/inspection rows, nie drifted.
4. `knowledge_search`, `knowledge_context`, `knowledge_explain`, `knowledge_impact` i
   `knowledge_entry_status` używają tej samej terminologii.
5. Nie dodawaj nowego MCP toola w fazie 1.
6. Nie zmieniaj protokołu ani limitów inputu.

### Krok 7 — release-cycle report w istniejącym `entry-coverage`

Pliki: `scripts/knowledge_store.py`, `scripts/copilot_role_guard.py`, testy parsera/guardów,
`curate-knowledge/SKILL.md`.

1. Rozszerz istniejące `entry-coverage`, zamiast tworzyć nowy command.
2. Dodaj opcjonalny argument:

   ```text
   --review-cycle-days <1..365>
   ```

   Domyślnie: 30.

3. Raport pozostaje read-only i nie pyta użytkownika.
4. Dodaj blok `maintenance`:

   ```json
   {
     "asOf": "<UTC timestamp>",
     "reviewCycleDays": 30,
     "policy": "age never expires approval",
     "counts": {
       "currentNoAction": 0,
       "olderCurrentNoAction": 0,
       "driftedDisclosureOnly": 0,
       "optionalRefresh": 0,
       "requiresDecision": 0
     },
     "optionalRefresh": [],
     "requiresDecision": []
   }
   ```

5. Klasyfikacja:
   - current, niezależnie od wieku → `currentNoAction`;
   - current starsze niż cykl → dodatkowo count `olderCurrentNoAction`, bez listy per Entry i bez
     pytania;
   - drifted młodsze niż cykl → `driftedDisclosureOnly`;
   - drifted starsze/równe cyklowi → `optionalRefresh`, nadal effective;
   - missing/unreadable/integrity-invalid → `requiresDecision` niezależnie od wieku.
6. `optionalRefresh` zawiera identity, reviewedAt, ageDays, lane i changed paths. Nie zawiera
   rekomendacji reapproval jako obowiązku.
7. `requiresDecision` zawiera identity, problem codes i paths.
8. Listy mają cap 50; counts zawsze opisują pełną populację i wynik jawnie podaje truncation.
9. Czas testuj przez wstrzykiwany/helperowy `now`, nie przez flaky sleep.
10. Zaktualizuj role guard allowlist dla nowego argumentu i test automatycznie porównujący argparse
    z allowlistą.
11. `curate-knowledge` instruuje: jeden batch report per release cycle, brak pytań dla current,
    opcjonalna decyzja maintainera tylko dla `optionalRefresh`, wymagane działanie tylko dla
    `requiresDecision`.

### Krok 8 — one-source cleanup konsumentów

Kanoniczny plik: `.github/skills/search-knowledge/SKILL.md`.

1. Ujednolić w nim:
   - effective lanes;
   - default retrieval;
   - main vs non-effective buckets;
   - citation boundary;
   - source drift advisory;
   - missing/unreadable integrity gap;
   - generic-bucket rule;
   - org usage jako osobną oś.
2. Usunąć wymóg reapproval jako repair zwykłego driftu.
3. Skille konsumenckie:
   - `.github/skills/check-against-principles/SKILL.md`;
   - `.github/skills/check-feature-coverage/SKILL.md`;
   - `.github/skills/adhoc-fix/SKILL.md`;
   - `.github/skills/generate-technical-documentation/SKILL.md`;
     mają wskazywać na `search-knowledge` i nie kopiować lane mechanics ani listy generic types.
4. W każdym konsumencie zostawić:
   - literalne `knowledge_context`;
   - literalne `hydrated` i lokalny skutek `hydrated: false`;
   - jedno zdanie opisujące obowiązek jego własnego outputu, np. unchecked class w matrix/fix
     note/review finding/documentation.
5. `check-against-principles` krok 7 zachowuje:
   - explicit non-effective states;
   - `approved-drifted` disclosure-only;
   - `entry-verify-citations --envelope` przed werdyktem.
6. `selected-files-knowledge` i `curate-knowledge` nie mogą nadal przedstawiać redraft/reapproval
   jako obowiązkowej reakcji na każdy drift. Drafting pozostaje dostępną decyzją maintainera.
7. `author-feature` zachowuje obecne przyjmowanie drifted binding i ma używać tej samej
   terminologii.

### Krok 9 — tool reachability dla reviewera

Pliki: `.github/agents/reviewer.agent.md`,
`.github/prompts/check-against-principles.prompt.md`, `scripts/validate_harness.py`, safety tests.

1. Usuń `tools:` z frontmatter promptu `check-against-principles`.
2. Reviewer agent pozostaje authority i ma:
   - `read`;
   - `search`;
   - `execute/runInTerminal`;
   - `knowledge/*`;
   - cztery istniejące Salesforce read-only review tools, włącznie z `review_soql_query`.
3. Nie dodawaj `ado-readonly/*`, `vscode/askQuestions`, write tools ani org mutation.
4. Role guard ma pozwalać reviewerowi dokładnie na:

   ```text
   python scripts/knowledge_store.py entry-verify-citations --envelope <repo-relative-path>
   ```

   oraz nadal odrzucać `entry-approve`, `entry-revoke`, `feature-approve` i inne mutacje.

5. Dodaj validator/test:
   - prompt nie ma własnego `tools:` override;
   - reviewer ma terminal, search, Knowledge i wymagane Salesforce review tools;
   - dokładna komenda w skillu jest osiągalna i guard-valid na POSIX/Windows invocation policy.

### Krok 10 — kontrakty i zapis decyzji

Pliki obowiązkowe:

- `docs/knowledge-one-file-contract.md`;
- `.ai/knowledge/README.md`;
- `.ai/memory/decisions-log.md`;
- `.github/skills/search-knowledge/SKILL.md`;
- `evals/agent-scenarios.yaml`;
- `.ai/repo-map.md` i `.ai/repo-map.json` po renderze.

W kontrakcie popraw co najmniej:

- §4 lifecycle/effectiveness: oba approved lanes effective;
- invalidation matrix: source drift daje advisory, nie utratę effectiveness;
- §8 shadowing/citation: drifted nadal może groundować;
- §14 anchor behavior: drifted citable z disclosure, missing nie;
- §15 index window: finalnym źródłem store-fresh status jest entry-status; brak mandatory rebuild
  tylko z powodu driftu;
- fragmenty nazywające drifted „not approved-current and must not be cited”.

W decisions log dodaj jeden wpis fazy 1 zawierający D1–D7, listę commitów, nazwane odstępstwo Set A,
wyniki bram i świadomie odłożone fazy 2–4. Nie przepisuj historycznych wpisów — log jest
append-only.

W `agent-scenarios.yaml`:

1. Zmień scenariusz drifted + expired org usage tak, aby:
   - repo-source Entry pozostało effective;
   - expired org numbers były nieużywalne i wymagały nowego probe;
   - agent nie mieszał tych dwóch osi.
2. Dodaj scenariusz missing source fragment → invalid/not-effective.
3. Dodaj scenariusz Entry starszego niż release cycle bez source drift → żadnego pytania i żadnej
   zmiany skuteczności.
4. Dodaj scenariusz old drifted → jeden batch optional refresh, brak per-entry blocker.

### Krok 11 — repo map i dokumentacja wygenerowana

1. Po finalnych zmianach uruchom:

   ```bash
   .venv/bin/python scripts/render_repo_map.py render
   ```

2. Zachowaj istniejące niezależne zmiany w `.ai/repo-map.json`; render ma odtworzyć mapę z
   aktualnych źródeł, nie ręcznie złożonego merge.
3. Sprawdź, czy `.ai/repo-map.md` zmieniło się semantycznie. Nie wymuszaj dotknięcia pliku, jeśli
   render nie zmienia treści.
4. Nie edytuj wygenerowanych plików ręcznie po renderze.

## 7. Szczegółowa macierz testów

### `tests/test_knowledge_store.py`

Wymagane przypadki:

1. current source → `approved-current`, effective true, bez advisory;
2. changed existing source → `approved-drifted`, effective true, SOURCE_DRIFT + path;
3. missing source → `not-effective`, effective false, SOURCE_FRAGMENT_MISSING;
4. unreadable source → `not-effective`, effective false, SOURCE_FRAGMENT_UNREADABLE;
5. drifted citation → verdict drifted, severity ok, effective true, advisory;
6. drifted envelope → invalid count zero;
7. digest mismatch → invalid mimo drift policy;
8. revoked/draft/not-effective → invalid;
9. Feature binding nadal akceptuje drifted;
10. release report: current old/new, drifted old/new, missing, list caps i deterministic age.

### `tests/test_knowledge_search.py`

Wymagane przypadki:

1. domyślne exact search znajduje drifted w `approvedResults`;
2. domyślne free-text search znajduje drifted;
3. drifted nie trafia do `nonCurrentResults`;
4. context umieszcza drifted relations w `parts`/`permissions`/`incoming`, nie w siblings;
5. explain i impact zachowują tę samą semantykę;
6. traversal może przechodzić przez effective drifted node;
7. draft/revoked/not-effective nadal wymagają explicit state i trafiają do inspection buckets;
8. `capabilities.defaultStates` zawiera oba approved lanes;
9. anchor source drift emituje jedno advisory bez `do not cite`, mandatory reapproval i mandatory
   rebuild;
10. missing source emituje integrity gap;
11. hydration failure nadal wyklucza wynik;
12. osobne cap budgets nie zmieniły się;
13. row lifecycle disclosure występuje raz i jest kompaktowe;
14. default result pozostaje deterministic po przebudowie indexu.

### Contract/MCP/safety tests

1. `tests/test_knowledge_contract.py` pinuje dokładną zasadę effective drifted i no-expiry-by-age.
2. `tests/test_knowledge_mcp_contract.py` pinuje descriptions/default states i brak nowego toola.
3. `tests/test_safety_hooks.py` pinuje reviewer terminal allow/deny.
4. Parser/guard contract pinuje `--review-cycle-days` i jego arity.
5. Repo-map tests nadal widzą ten sam Set A; nie zmieniaj membership bez potrzeby.
6. Nie dodawaj testów dziedziczących z test-bearing classes; globalny architecture test ma pozostać
   zielony.

### Testy negatywne, które muszą pozostać zielone

- hand-built search/context citation nadal nie jest citable receipt;
- draft i revoked nigdy nie stają się effective;
- tampered Entry nie jest „tylko drifted”;
- entry file digest mismatch nadal wymaga rebuild/retry lub odrzucenia zgodnie z istniejącą
  hydration policy;
- missing source nie jest downgraded do advisory;
- expired org usage nie wraca do wyników tylko dlatego, że Entry jest approved;
- reviewer nie zyskuje Knowledge mutation ani Salesforce write tools;
- maintenance report niczego nie zapisuje.

## 8. Kryteria akceptacji funkcjonalnej

Faza 1 jest zakończona tylko wtedy, gdy wszystkie poniższe są prawdziwe:

1. Jedna stała/helper definiuje effective Entry lanes.
2. `approved-drifted` jest domyślnie wyszukiwane na wszystkich czterech retrieval surfaces.
3. Wszystkie main approved buckets zawierają current i drifted.
4. Drifted citation ma `effective: true`, nie zwiększa invalid count i nie wymusza reapproval.
5. Drift advisory zawiera identity/path i pojawia się najwyżej raz na logiczny wynik/sekcję.
6. Missing/unreadable source jest `not-effective` z machine-readable code.
7. Wiek Entry nigdy nie zmienia lane ani effectiveness.
8. `entry-coverage --review-cycle-days 30` generuje jedną batch maintenance summary.
9. Current older than cycle nie trafia na listę pytań.
10. Old drifted trafia wyłącznie do optional refresh.
11. `search-knowledge` jest jedynym źródłem generic-bucket/lane/citation procedure.
12. Set A nadal zawiera literalne `knowledge_context` i `hydrated` na każdej pinowanej powierzchni.
13. `check-against-principles` może rzeczywiście uruchomić envelope verifier jako reviewer.
14. Prompt nie nadpisuje tool surface reviewera.
15. Nie zmieniono żadnego schema pliku, lifecycle enum ani output-envelope.
16. Nie zapisano żadnego Entry, Feature ani ledgera podczas testów na realnym workspace.

## 9. Bramy końcowe

Uruchomić w tej kolejności:

```bash
git diff --check

.venv/bin/python -m unittest \
  tests.test_knowledge_store \
  tests.test_knowledge_search \
  tests.test_knowledge_contract \
  tests.test_feature_knowledge \
  tests.test_knowledge_mcp_contract \
  tests.test_safety_hooks \
  tests.test_guard_parser_contract \
  tests.test_repo_map

.venv/bin/python scripts/render_repo_map.py render
.venv/bin/python scripts/validate_harness.py
.venv/bin/python scripts/run_evals.py

npm run prettier:verify
npm run lint

.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Następnie wykonać sweeps:

```bash
rg -n "re-approve before citing as current|approved-current rows only|drifted.*must not be cited|drifted.*non-effective" \
  scripts .github .ai/knowledge docs/knowledge-one-file-contract.md evals

rg -n "Generic-bucket types|generic-bucket remainder|Settings, Letterhead, Group" \
  .github/skills .github/agents .github/prompts

git status --short
```

Interpretacja sweeps:

- pierwszy nie może znaleźć aktywnej instrukcji przeczącej D1–D4; historyczne docs poza aktywnym
  kontraktem mogą pozostać, ale agent musi je sklasyfikować;
- pełna lista generic-bucket może pozostać tylko w kanonicznym `search-knowledge` i historycznych
  dokumentach; konsumenci mają pointer + własny obowiązek outputu;
- `git status` nie może pokazać zmian w live Knowledge entries, ledgerach, local config ani source
  metadanych wynikających z testów.

Jeżeli repo ma standardowy npm audit gate, uruchom również:

```bash
npm audit --omit=dev --audit-level=high
```

## 10. Plan commitów

Nie twórz jednego mega-commita. Zalecana kolejność:

1. `Knowledge core: separate approval effectiveness from source freshness`
   - store helper, effective fields, missing/unreadable, citation verifier;
   - odpowiadające unit tests.
2. `Knowledge retrieval: serve approved-drifted by default`
   - search buckets, anchor advisory, MCP descriptions;
   - search/MCP tests.
3. `Knowledge maintenance: add read-only release-cycle summary`
   - entry-coverage flag/report, role guard, tests, curator instructions.
4. `Knowledge consumers: align one-source rules and reviewer tools`
   - skille, reviewer/prompt tools, validator/safety tests.
5. `Knowledge policy: record phase-1 decisions and refresh repo map`
   - contract, README, decisions log, eval scenarios, generated map.

Jeżeli istniejące niezacommitowane zmiany uniemożliwiają czysty podział bez mieszania cudzej pracy,
nie używaj partial staging na ślepo. Zachowaj bezpieczną, opisaną granicę commitów i w raporcie nazwij
pliki zawierające wcześniejszy diff.

Nie pushuj i nie twórz PR bez osobnej instrukcji użytkownika. Lokalne commity są dozwolone przez ten
plan tylko wtedy, gdy `/goal` dostał polecenie implementacji i workspace nie wymaga dodatkowej zgody.

## 11. Oczekiwany raport końcowy agenta

Raport ma zawierać:

1. Werdykt: COMPLETE albo BLOCKED z dokładnym powodem.
2. Aktualny branch, HEAD i lista nowych commitów.
3. Krótką tabelę D1–D7 → miejsce implementacji → test dowodowy.
4. Pliki zmienione według kategorii: runtime, contracts, skills/prompts, tests, generated.
5. Wyniki każdej bramy z sekcji 9, włącznie z czasem pełnego suite.
6. Potwierdzenie:
   - zero schema changes;
   - zero live Knowledge/ledger writes;
   - zero Salesforce/ADO calls;
   - zero nowych lifecycle lanes;
   - brak push/PR, jeśli nie zlecono.
7. Listę pozostałych ograniczeń fazy 1:
   - rows pozostają index-fresh do fazy live overlay;
   - semantic facts diff nie istnieje;
   - optional refresh niczego automatycznie nie aktualizuje.
8. Każde odstępstwo od planu z reasoningiem i testem kompensującym.

## 12. Warunki STOP

Agent ma zatrzymać implementację i zgłosić blocker zamiast zgadywać, jeśli:

1. Aktualny local diff nakłada się na ten sam hunk i nie da się zachować obu intencji.
2. Zmiana wymaga modyfikacji `knowledge-entry.schema.json`, output-envelope albo nowego lifecycle
   lane.
3. Implementacja wymaga zapisu Entry/ledger w read path.
4. Prompt inheritance w obsługiwanym VS Code host nie pozwala usunąć `tools:` bez utraty wymaganych
   capabilities i nie istnieje repo-local dowód bezpiecznego zachowania.
5. Reviewer potrzebowałby ADO wildcard albo write-capable toola do wykonania tej procedury.
6. Baseline ma istniejący failure uniemożliwiający odróżnienie regresji fazy 1.
7. Source-missing nie może zostać rozróżnione od changed source bez zmiany trwałego Entry formatu.
8. Pełny suite odkrywa konflikt z aktywnym kontraktem spoza wymienionego zakresu.

Nie jest warunkiem STOP:

- duża liczba testów do aktualizacji;
- potrzeba regeneracji repo map;
- drift historycznych dokumentów;
- to, że `origin/main` jest za lokalnym `main`;
- wydłużenie pracy przez pełny suite.

## 13. Szacunek dla agenta

| Pakiet                               |     Szacunek |
| ------------------------------------ | -----------: |
| preflight + core lane/source changes |      1,5–3 h |
| retrieval buckets + MCP              |      1,5–3 h |
| release-cycle report                 |      1,5–3 h |
| skills/tools/contracts/decisions     |        1–2 h |
| test hardening + pełne bramy         |        2–4 h |
| razem                                | **7,5–15 h** |

Szacunek zakłada pojedynczego sprawnego agenta, aktualny kontekst repo i brak warunku STOP. Nie jest
deadline'em ani powodem do pomijania testów.

## 14. Definicja „nie zrobione w fazie 1”

Po zakończeniu fazy 1 nadal będzie prawdą:

- system nie wie automatycznie, czy zmiana source zmieniła zatwierdzone facts;
- drifted Entry pozostaje effective z advisory niezależnie od semantic materiality;
- row-level lane może być index-fresh do momentu live status check;
- maintainer może wybrać refresh, ale executor nie wykona automatycznego source-pin update;
- nie ma automatyzacji miesięcznej — report jest uruchamiany jawnie w release workflow.

Te ograniczenia są świadome. Celem fazy 1 jest usunięcie false blockerów i ceremonii przy zachowaniu
uczciwego disclosure, nie budowa kompletnego systemu semantic drift.
