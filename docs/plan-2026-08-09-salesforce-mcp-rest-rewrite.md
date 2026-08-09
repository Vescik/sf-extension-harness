# Plan — przepisanie fasady Salesforce MCP na Python + bezpośredni REST

Data: 2026-08-09
Status: **plan do realizacji, bez implementacji.** Nic z tego nie zostało jeszcze wykonane.
Zweryfikowano: 2026-08-09, sześciopunktowy pas weryfikacyjny (kod repo + web) — poprawki
naniesione w tej wersji; miejsca zmienione względem pierwszego szkicu oznaczone „[W]".
Autor zapisu: Claude (chat), na podstawie rozmowy z ownerem i researchu z 2026-08-09
Dokument nadrzędny: `plan-2026-08-07-context-first-architecture.md` — ten plan realizuje
jego zasadę „kod chroni tylko nieodwracalne krawędzie" wobec najcięższego mechanizmu,
jaki został po starej architekturze: `scripts/salesforce_review_server.mjs` (~1700 linii,
dual-source reconciliation, dziecko `@salesforce/mcp` per call).

Kryterium doboru bez zmian: **treść albo obserwacja, zero procesu.** Jedyny kod, który
zostaje, to ściany nieodwracalnych krawędzi (non-production, read-only) — wszystko inne
z fasady wylatuje.

---

## 1. Problem — zmierzony, nie przypuszczany

Objaw: `MCP timeout` przy kilku wywołaniach narzędzi pod rząd; pojedyncze SOQL działa.
Cztery przyczyny, wszystkie potwierdzone (kod / upstream trackery):

| # | Przyczyna | Dowód |
|---|---|---|
| P-1 | Świeże dziecko `@salesforce/mcp` (boot oclif/sfdx-core) **na każdy call**, ubijane po callu | `withMcp()` w `salesforce_review_server.mjs` |
| P-2 | Dodatkowy SOQL tożsamościowy (`SELECT Id, IsSandbox FROM Organization`) przez to dziecko **przed każdym** właściwym zapytaniem | `reviewSoqlQuery()` |
| P-3 | `commandTimeoutSeconds` walidowany do 5–60 s — podnoszenie limitu w configu powyżej 60 było niemożliwe po cichu | walidacja policy w serwerze |
| P-4 | Klient (VS Code / Copilot CLI) ma twardy ~60 s timeout, którego config **nie podnosi** | TS SDK `DEFAULT_REQUEST_TIMEOUT_MSEC=60000`; [copilot-cli #1535](https://github.com/github/copilot-cli/issues/1535), [#172](https://github.com/github/copilot-cli/issues/172); brak ustawienia w VS Code ([vscode-copilot-release #14130](https://github.com/microsoft/vscode-copilot-release/issues/14130)) |

Wniosek projektowy: timeoutu nie da się „podnieść" — trzeba zejść **pod** niego.
Każdy call musi kosztować co najwyżej jeden round-trip HTTP do orga, zero bootów procesów.

## 2. Tabela decyzji

| # | Decyzja | Opcje | Rekomendacja | Koszt utrzymania |
|---|---|---|---|---|
| D-1 | Check orga | (a) tylko na starcie + po każdym odświeżeniu tokenu po 401; (b) tylko na starcie; (c) usunąć całkiem | **(a)** — koszt per call: zero; refresh nie może po cichu przepiąć się na inny org. (c) oszczędza milisekundy startu i osłabia jedyną twardą ścianę „never production" — odrzucone | ~40 linii, raz napisane; regex hostów już istnieje |
| D-2 | Kontrakt envelope | (a) `schemaVersion: 2` — minimalna rewizja `sources`/`reconciliation`, pola czytane przez konsumentów bez zmian; (b) emulować stary dual-source kształt z jednego transportu; (c) pełny redesign schematu | **(a)**. (b) to kłamstwo w danych (deklarowanie źródła MCP, którego nie ma) — odrzucone. (c) rusza kontrakty `knowledge_store` bez potrzeby — odrzucone | [W] schemat evidence **+ `schemas/harness-config.schema.json` + `config/harness.example.json`** (`requireDualSource` jest przybite w trzech miejscach — §4) + testy pinujące; `knowledge_store.py` nietknięty; `salesforce_review_client.py` — tylko linia startu procesu (§4) |
| D-3 | Warstwa HTTP | (a) `requests` (pooling/keep-alive, retry, proxy/CA korporacyjne za darmo); (b) własny wrapper na `http.client` | **(a)** — skrypty repo już wymagają paczek spoza stdlib (PyYAML, jsonschema); (b) to ~200 linii własnego kodu sieciowego do utrzymania | jedna pozycja w wymaganiach; zero własnego kodu sieciowego |
| D-4 | Trwały audit log JSONL wywołań | (a) tak, z retencją; (b) nie — jedna linia timingu na stderr per call; pomiar do weryfikacji tymczasowy | **(b)**. Własna wcześniejsza propozycja (a) zakwestionowana zgodnie z regułą „content over process": stały log = nowy mechanizm z polityką retencji, a luka, którą łata (dowody latencji), jest tymczasowa. Wraca tylko przy konkretnej obserwowanej potrzebie | zero (stderr już jest kanałem logów) |
| D-5 | Wygaszenie starego serwera | (a) usunąć w tej samej fazie; (b) równolegle za flagą do czasu re-weryfikacji | **(a)** — pojedynczy maintainer, weryfikacja żywa i tak jest w planie (§6); flaga to proces i drugi kod do utrzymania przez okres przejściowy | ujemny: −1700 linii, −1 pin wersji vendora |
| D-6 | Cache paragonów `.cache/salesforce-review/` | (a) usunąć w całości; (b) zachować | **(a)** — grep potwierdza: **nic w repo nie czyta `receiptRef`**; żywym kontraktem jest wyłącznie kształt envelope zwracany in-band. `entry-org-attach` woła fasadę synchronicznie i dostaje envelope bezpośrednio | ujemny: −TTL-sweep, −pisanie plików |
| D-7 | Narzędzie `explain_query` na endpointcie **Beta** | (a) dodać, ryzyko beta zaakceptowane; (b) nie dodawać do czasu GA | **(a)** — endpoint `GET /query/?explain=` („Get Feedback on Query Performance") nosi w dokumentacji Salesforce pełny disclaimer „Beta Service" (zweryfikowane 2026-08-09). Ryzyko niskie i zaakceptowane: narzędzie czysto diagnostyczne, żadna logika downstream nie zależy od kształtu odpowiedzi — zmiana/wycofanie endpointu psuje jedno narzędzie, nie kontrakt | 1 handler (~30 linii); przy wycofaniu endpointu narzędzie zwraca błąd wykonania, reszta serwera nietknięta |

## 3. Architektura docelowa

`scripts/salesforce_review_server.py` — jeden plik, surowa pętla NDJSON JSON-RPC
(protokół `2025-06-18`, jak dziś; bez SDK — patrz §5).

**Start (raz na sesję serwera, nie per call):**
1. `sf org auth show-access-token --json -o <alias>` → token. **Uwaga — zmiana łamiąca
   CLI z 2026-05-27**: `sf org display` redaguje token także w `--json`
   ([forcedotcom/cli #3560](https://github.com/forcedotcom/cli/issues/3560));
   przepisy z internetu parsujące `org display` są martwe. Obie komendy same robią
   `refreshAuth()` przed wydrukiem (zweryfikowane w źródłach plugin-org).
   [W] Komenda istnieje od **CLI 2.136.8 / plugin-org 5.11.0** — serwer waliduje na
   starcie `sf version` ≥ 2.136.8 (loud fail z komunikatem „zaktualizuj sf CLI");
   samo `--json` wycisza prompt bezpieczeństwa (bez niego w headless wisi 30 s i pada).
   [W] **Spawn `sf` na Windows**: Python nie ma blokady Node'a (CPython po BatBadBut
   zmienił tylko dokumentację), więc port maszynerii ComSpec nie jest potrzebny — ale
   quoting `list2cmdline` jest błędny dla cmd.exe, więc preferowane wywołanie omija
   cmd.exe całkowicie: `node <instalacja-sf>/bin/run.js …` (shim `sf.cmd` to jedna
   linia robiąca dokładnie to), z fallbackiem na pełną ścieżkę `sf.cmd`/`sf.exe` w
   rezolucji where.exe (port `scanPathForSf` z `.mjs` **1:1** — `shutil.which` odpada:
   bezwarunkowo preferuje bieżący katalog i nie pomija `.ps1`) + port
   `assertPlainCliArgument` + argumenty wyłącznie regex-walidowane (aliasy) i literały.
   Ścieżka `run.js` używana tylko po runtime existence-check (node realny, `run.js`
   istnieje obok rozwiązanego `sf.cmd`; shim dryfuje między wydaniami — treść z 2026
   niezweryfikowana zdalnie); inaczej fallback na `sf.cmd`.
2. `sf org display --json -o <alias>` → `instanceUrl`, `apiVersion`, org id, username
   (te pola pozostają nieredagowane — potwierdzone w źródłach plugin-org).
3. Check orga (D-1): host pasuje do `NON_PRODUCTION_HOST` (istniejący regex), org id
   zgodny z `config/harness.local.json` i spoza denied-list. Zero dodatkowych
   round-tripów — dane już są w wyjściu CLI. Tożsamość **zamrożona na sesję**.
4. Jedna sonda `GET /services/data` — token żyje + baseline latencji na stderr.

**Per call:** jeden request przez trwałą `requests.Session` (TLS handshake raz na
sesję). Budżet pod twarde 60 s klienta: connect ~10 s, read ~40 s, **bez retry na
read-timeout** — zamiast tego błąd wykonania (`isError: true`) z czasem, który minął,
i sugestią zawężenia zapytania. Na `401 INVALID_SESSION_ID`: jednorazowo ponów
`show-access-token`, **wykonaj żywą sondę tożsamości** (identity SOQL nowym tokenem,
porównanie z zamrożonym org id — dane z auth file nie wystarczą, bo mogą być
niespójne z tokenem), powtórz request; niezgodność org id ⇒ serwer przechodzi w
fail-closed (każdy kolejny call = błąd `IDENTITY_ORG_ID_MISMATCH`); jeśli refresh
padł (`invalid_grant`) — błąd wykonania „uruchom `sf org login web`".
[W] **Uśpienie laptopa / zerwany VPN:** martwe połączenie w puli objawia się dwojako —
RST przy wysyłce (szybki `ConnectionError`) albo half-open blackhole (wisi do read
timeoutu ~40 s; connect-timeout NIE działa, bo nowego connectu nie ma). Obsługa:
na `ConnectionError` (nie na read-timeout) — zamknij pulę (`session.close()`),
odtwórz i **jednorazowo** ponów request (wszystkie nasze wywołania to idempotentne
GET-y); najgorszy przypadek pozostaje ograniczony przez read timeout poniżej budżetu
klienta.

**Windows (maszyny zespołu):** stdin/stdout w trybie binarnym (domyślny tryb tekstowy
zamienia `\n`→`\r\n` i psuje framing **tylko na Windows**), `PYTHONUTF8=1` w bloku
`env` w `.vscode/mcp.json`, flush po każdej wiadomości, start serwera przez `python`
(realny exe — blokada EINVAL Node'a nie dotyczy startu; bezpieczny spawn `sf` z wnętrza
serwera opisany w kroku 1 startu).

[W] **Współbieżność — zweryfikowana, nie hipotetyczna:** VS Code od 2025-10 celowo
puszcza wywołania narzędzi MCP **równolegle** do jednego serwera
([vscode-copilot-chat PR #1406](https://github.com/microsoft/vscode-copilot-chat/pull/1406);
klient MCP w VS Code nie ma kolejki per serwer), a Copilot CLI ma parallel tool calls
od 0.0.349 i **usunął opt-out** przy GA 0.0.418. Czysto sekwencyjna pętla odtworzyłaby
dzisiejszy objaw: wolne SOQL (~40 s) blokuje zakolejkowane równoległe wywołanie aż po
60-sekundowy timeout klienta. Dlatego: pętla czyta i buforuje żądania na bieżąco,
`tools/call` idzie do **małej puli wątków** (limit ~4), każda odpowiedź pisana pod
lockiem jako jedna atomowa linia; `notifications/cancelled` = tłumienie odpowiedzi po
id. `requests.Session`/pula urllib3 są przy takim użyciu bezpieczne wątkowo; stan
serwera (token, tożsamość) chroniony jednym lockiem przy refresh po 401.

[W] **Przebieg klienta wewnętrznego:** `salesforce_review_client.py` wysyła
`initialize` + `tools/call` jednym wsadem, **nigdy nie wysyła
`notifications/initialized`** i zamyka stdin — serwer nie bramkuje `tools/call` na
initialized, odpowiada na oba żądania i kończy się czysto na EOF.

**Narzędzia** (wszystkie `readOnlyHint: true`; egzekwowaniem jest brak handlerów
zapisu, nie adnotacja):

| Narzędzie | Wywołanie | Uwagi |
|---|---|---|
| `review_soql_query` | `GET /query` lub `/tooling/query` | nazwa i envelope bez zmian (kontrakt §4); verbatim pass-through (decyzja ownera 2026-08-04 w mocy); paginacja `nextRecordsUrl` do limitu wierszy, potem jawny komunikat truncation |
| `review_object_contract` | `/tooling/query` (profile `objectEntity`/`objectFields` z policy) **+ jeden `GET /sobjects/<x>/describe`** | [W] lista pól z pinowanych zapytań FieldDefinition jak dziś; describe **uzupełnia wyłącznie traity** `sourceExclusive` (`unique`/`externalId`/`createable`/`updateable`), które stary serwer brał z nogi CLI, a FieldDefinition ich nie ma (żywo 2026-08-05) — decyzja ownera 2026-08-09 (odkrycie z przeglądu po F-1: „identyczny kształt faktów" było przesadzone, traity by znikły). W v2 traity idą pod `sourceExclusive.rest` (schemat: `oneOf` `{cli,mcp}` \| `{rest}` — klucz „cli" przy danych z REST byłby kłamstwem jak w D-2b); bezpieczne, bo żaden kod nie czyta `sourceExclusive`. Describe cache'owany `If-Modified-Since`, ten sam allowlist. Describe jako *zamiennik* pinowanych zapytań pozostaje odrzucony (§5) |
| `review_installed_packages` | `/tooling/query` (profil z policy) | jak dziś, jednym transportem |
| `review_org_identity` | zamrożony dowód ze startu | zero wywołań do orga |
| `review_configured_orgs` | config lokalny | bez zmian (gated jak dziś) |
| `org_limits` *(nowe, tanie)* | `GET /limits` | zużycie `DailyApiRequests` widoczne dla agenta; 5 linii kodu |
| `explain_query` *(nowe, D-7)* | `GET /query/?explain=<SOQL>` (i `/tooling/query/?explain=` przy `tooling=true`) | zwraca **surową tablicę `plans[]` z API bez żadnej interpretacji** po stronie serwera (koszt/kardynalność ocenia agent w kontekście — content over process); nie wykonuje zapytania, zero wierszy; [W] **przechodzi przez ten sam `describeComposedSoql` co `review_soql_query`** (skan FROM + allowlist obiektów, gdy skonfigurowany — inaczej explain byłby obejściem scopingu); endpoint Beta — ryzyko zaakceptowane w D-7; wsparcie wariantu Tooling do potwierdzenia żywo w F-2 (strona docs go nie rozstrzyga) |

Wylatuje: dziecko `@salesforce/mcp` + pin `0.30.15`, per-call SOQL tożsamościowy,
dual-source reconciliation z porównaniami MISMATCH, cache paragonów, knob
`commandTimeoutSeconds` (zastąpiony jawnym budżetem HTTP).

## 4. Kontrakt envelope — co jest żywe i co się zmienia

Żywi konsumenci: `salesforce_review_client.py` (walidacja generyczna: schemat
Draft2020-12 + digest sha256 kanoniczny) i `knowledge_store.py:command_entry_org_attach`.
[W] Prześledzony pełny odczyt (funkcja + wszystkie DERIVERS): bramki
`target.{environment, nonProduction, expectedOrgIdMatched}` (environment ≠ `dynamic`
i równy configowi), `status == "VERIFIED"`, `completeness.complete`; porównania
`facts.soqlQuery.{queryDigest, fromObjects}`; **wszystkie derivery czytają wyłącznie
`facts.soqlQuery.records`** — `useToolingApi` i `matched` są wymagane przez schemat,
ale nieczytane; `receiptRef` opcjonalny i nieczytany. Dodatkowo attach wkleja **cały
envelope verbatim** do trwałych paragonów org-usage (`receipt_probes[...]["envelope"]`)
— envelope v2 trafi do przyszłych paragonów; stare nie są re-walidowane, kolizji brak.

[W] `salesforce_review_client.py` ma **zahardkodowaną** ścieżkę
`scripts/salesforce_review_server.mjs` i spawn `["node", script, "--org", alias]` —
wymaga jednej zmiany: linii startu procesu (na `[sys.executable, "scripts/
salesforce_review_server.py", "--org", alias]`). Cała logika walidacji envelope
zostaje bez zmian. Uwaga architektoniczna (poza zakresem): klient spawnuje serwer
per probe, więc attach z N probe'ami płaci N× koszt startu (2 wywołania `sf`) —
akceptowalne dla rzadkiej, gated operacji; ewentualne batchowanie probe'ów w jednej
sesji to osobna, przyszła zmiana klienta, nie serwera.

`schemaVersion: 2` (D-2) zmienia wyłącznie to, co opisywało podwójny transport:
- `sources`: wymagane `{cli, mcp}` → `{cli, rest}` (CLI = dowód tożsamości ze startu,
  rest = transport zapytania); kształt bloku źródła bez zmian (kind/version/complete/retrievedAt).
- `reconciliation.status`: enum zostaje, nowy serwer emituje `SINGLE_SOURCE` /
  `IDENTITY_MATCH_ONLY` (oba już w enumie) — `MATCH`/`MISMATCH` przestają być emitowane,
  ale w schemacie zostają (stare envelope w testach dalej walidują).
- `completeness.dualSource`: zawsze `false` (pole zostaje — konsument go nie gate'uje).
- Wszystkie pola czytane przez `entry-org-attach` — **bajt w bajt bez zmian.**

[W] **`requireDualSource` jest przybite w trzech miejscach** — walidacja startowa
serwera (`=== true` albo CONFIG_INVALID), `schemas/harness-config.schema.json`
(pole *wymagane*) i `config/harness.example.json` — kasowanie dual-source obejmuje
wszystkie trzy (pole znika ze schematu i z example; walidacja przestaje go żądać).

Pliki dotknięte: `schemas/salesforce-org-review-evidence.schema.json`,
`schemas/harness-config.schema.json`, `config/harness.example.json`, nowy serwer,
testy pinujące oba schematy, **jedna linia** w `salesforce_review_client.py` (start
procesu). `knowledge_store.py` — **zero zmian** (attach czyta pola, które nie drgnęły).

## 5. Celowo nie dodane

- **SDK MCP (oficjalne / FastMCP)** — `pip install mcp` to ~25 paczek z kompilowanym
  `pydantic-core` (wrogie zablokowanym Windowsom), a oba SDK są dwa tygodnie po
  łamiącym v2. Surowa pętla NDJSON to wzorzec, który repo już utrzymuje w JS.
- **Bezpośredni refresh grant `PlatformCLI`** (POST na `/services/oauth2/token` bez
  sekretu) — mechanicznie pewny ze źródeł sfdx-core, ale nieudokumentowany dla stron
  trzecich; refresh przez ponowne wywołanie CLI wystarcza i nie dotyka tokenów at rest.
- **Czytanie `~/.sfdx/*.json`** — AES-GCM + klucz w OS credential store; reimplementacja
  per-OS to dokładnie ten rodzaj mechanizmu, którego nie chcemy utrzymywać.
- **Trwały audit log JSONL** (D-4b) — stderr wystarcza; wraca tylko przy obserwowanej luce.
- **Proaktywny refresh tokenu** — endpoint nie zwraca `expires_in`; reaktywne 401 wystarcza.
- [W] **Pełny async/asyncio** — mała pula wątków z lockiem na stdout (§3) wystarcza;
  asyncio wciągnąłby przepisanie warstwy HTTP i nic nie daje przy ~4 równoległych callach.
  (Pierwotny wpis „bez wielowątkowości" skreślony: równoległe `tools/call` od VS Code
  i Copilot CLI są zweryfikowanym faktem, nie hipotezą — §3.)
- [W] **Describe jako zamiennik pinowanych zapytań FieldDefinition** — odrzucony:
  zmieniałby kształt faktów i porzucał profile z policy. (Doprecyzowanie 2026-08-09:
  describe jako *uzupełnienie* traitów `sourceExclusive` został przyjęty — §3 —
  bo bez niego traity CLI-only zniknęłyby z kontraktu obiektu; lista pól nadal
  płynie wyłącznie z pinowanych zapytań.)
- **Retry na read-timeout** — zjadłby budżet 60 s klienta; błąd sterujący jest lepszy.
- **Auto-chainowanie `explain_query` przed `soql_query`** — `explain_query` jest
  narzędziem jawnym, wywoływanym osobno i tylko na wyraźne żądanie agenta.
  Automatyczne poprzedzanie każdego zapytania explainem podwoiłoby round-tripy per
  query i podważyło cały sens tego rewrite'u (mniej wywołań, nie więcej). Serwer też
  niczego z `plans[]` nie interpretuje — ocena selektywności to praca agenta w
  kontekście, nie logika serwera.
- **Protokół `2026-07-28`** — klienci negocjują `2025-06-18`; goni się go osobno, nie
  przy okazji. (Nowy serwer i tak nie trzyma stanu z handshake'u — jest gotowy.)
- **Tryb side-by-side ze starym serwerem** (D-5b) — flaga to proces; weryfikacja żywa
  jest w §6.
- **Named queries zamiast verbatim SOQL** — decyzja ownera 2026-08-04 (verbatim) w mocy.

## 6. Fazy i koszty

| Faza | Zakres | Koszt jednorazowy |
|---|---|---|
| F-1 | [W] Schemat evidence v2 **+ `harness-config.schema.json` i `harness.example.json`** (usunięcie `requireDualSource`) + aktualizacja testów pinujących oba schematy; `py_compile`/walidacja schematów | ~0,5 dnia |
| F-2 | [W] `salesforce_review_server.py` (pętla NDJSON z pulą wątków i lockiem stdout + warstwa REST + check startowy + **walidacja CLI ≥ 2.136.8** + spawn `sf` przez `node bin/run.js` z fallbackiem where.exe) + **jedna linia** w `salesforce_review_client.py`; unit testy: harness subprocess-pipe (stdlib), mock HTTP (401-replay z re-walidacją org-id, paginacja, truncation), regresja CRLF, tłumienie odpowiedzi po `notifications/cancelled`, **przebieg wsadowy klienta** (initialize+tools/call bez `initialized`, EOF), **2 równoległe wolne calle** (oba odpowiedziane, linie atomowe); **wymiana `tests/test_salesforce_review.py`** (mockowała dzieci CLI/MCP starego serwera); handler `explain_query` (surowy passthrough `plans[]`, ten sam skan FROM/allowlist co SOQL) + żywe potwierdzenie, czy wariant `/tooling/query/?explain=` w ogóle działa (docs nie rozstrzygają — jeśli nie, parametr `tooling` zwraca błąd wykonania z wyjaśnieniem); [W] jawny handler braku `requests`: `ImportError` na starcie ⇒ jednoznaczny komunikat na stderr („requests nie jest zainstalowane — patrz SETUP") + exit 1, plus linia kontrolna w preflight/`first_launch.py`, żeby brak zależności wyszedł przy setupie, nie przy pierwszym callu; [W] uzupełnienie traitów object-contract przez describe (decyzja b, 2026-08-09) + edycja schematu: `sourceExclusive` dostaje `oneOf` `{cli,mcp}` \| `{rest}` z testem pinującym w `test_evidence_schema_v2.py` | ~2–2,5 dnia |
| F-3 | [W] `.vscode/mcp.json` (command→python, env `PYTHONUTF8`), teksty sterujące narzędzi, `first_launch.py`/preflight jeśli pinują stary serwer, **sweep tekstów „dual-source"/„Salesforce MCP transport"** w `.github/` (m.in. `investigate-object.prompt.md`), `docs/grounding-architecture.md`, `docs/compatibility.md`, `.ai/contracts/tool-capabilities.md`, SETUP.md | ~0,5–1 dzień |
| F-4 | [W] Usunięcie `.mjs` serwera + pinu `@salesforce/mcp` + cache paragonów (launcher `start_salesforce_mcp.mjs` ZOSTAJE — odstępstwo F-3: resolver interpretera, wzorzec knowledge; mcp.json nie umie ścieżek per-platforma); pełny gate (`validate_harness.py`, unittest, `run_evals.py`); **weryfikacja żywa** na wolnym orgu: sekwencja wielu calli, która dziś reprodukuje timeout; wpisy do `.ai/memory/decisions-log.md` (D-1…D-6) i RESULTS-LOG w warsztacie | ~0,5–1 dzień |

Koszt utrzymania po wszystkim: **jeden plik .py zamiast 1700 linii .mjs + pin wersji
vendora + sweep cache'u**; jedna zależność (`requests`); zero procesów per call.

### 6a. Rollback [W]

Plik jest safety-critical, a D-5 odrzuciło tryb side-by-side — więc ścieżką odwrotu
jest **git, nie flaga**:

- Każda faza F-1…F-4 ląduje jako **jeden rewertowalny commit** (konwencja pinów:
  stary→nowy w wiadomości), F-4 zawiera kasację `.mjs` + pinu vendora.
- **Procedura odwrotu** (showstopper znaleziony w żywych testach harness-lab):
  `git revert` commitu F-4 (przywraca `.mjs`, launcher i pin w `package.json`) →
  `npm install` (odtwarza `@salesforce/mcp`) → przywrócenie `mcp.json`/linii startu
  klienta (są w tym samym commicie F-4) → `validate_harness.py` + unit suite muszą
  być zielone na przywróconym stanie.
- Schemat evidence v2 **przyjmuje `schemaVersion` 1 i 2** (enum) właśnie po to, żeby
  revert samego serwera nie wymagał jednoczesnego revertu F-1 — stary serwer emituje
  v1, która dalej waliduje. Enum zwężamy do `[2]` osobnym commitem dopiero po
  przejściu wszystkich testów ukończenia.
- Zero stanu do odwracania poza repo: serwer jest read-only, w orgu nic nie
  powstaje; jedyny stan lokalny (cache paragonów) i tak jest gitignorowany.

### 6b. Bilans kodu w liczbach [W]

**Znika:**
- `scripts/salesforce_review_server.mjs` — **1 708 linii**
- `scripts/start_salesforce_mcp.mjs` — **94 linie**
- pin `"@salesforce/mcp": "0.30.15"` z `package.json` (+ poddrzewo node_modules)
- kod sweep/TTL cache'u paragonów (wliczony w powyższe 1 708)

**Wymieniane (nie liczone jako zysk):** `tests/test_salesforce_review.py` —
**1 361 linii** mockujących dzieci CLI/MCP starego serwera → nowa suita o
porównywalnym rozmiarze (mock HTTP zamiast mock procesów).

**Dochodzi:** `scripts/salesforce_review_server.py` — szacunkowo **600–900 linii**
(ręczna pętla JSON-RPC ~150 linii wzorowana na sprawdzonej z `knowledge_mcp_server.mjs`;
warstwa REST + narzędzia + walidacja configu + porty z listy niżej); **bez** audit
logu (D-4: stderr) i **bez** SDK. Netto: około **−1 000 linii** produkcyjnego kodu
i jeden pin wersji vendora mniej.

### 6c. Kod przenoszony 1:1 — portuj, nie pisz z pamięci [W]

Każda z tych rzeczy jest hard-won (wersje wcześniejsze zawiodły albo semantykę
potwierdzono żywo) — port ma zachować zachowanie co do znaku, z testem przy każdej:

1. **`containsSensitiveMaterial` + zwolnienie `sensitiveGateExempt`** — brama
   redakcji: każdy envelope poza `review_soql_query` (zwolnienie = decyzja ownera
   2026-08-04) jest skanowany rekurencyjnie po kluczach (`accesstoken`,
   `refreshtoken`, `sfdxauthurl`, `authorization`, `clientid`, `username`, `orgid`,
   `organizationid`, `instanceurl`) i wartościach (regexy: `Bearer …`, `force://`,
   `00D…` org id, e-mail); trafienie ⇒ envelope BLOCKED z
   `SENSITIVE_OUTPUT_DETECTED`. **Zostaje w mocy w nowym serwerze** — jest tym
   ważniejsza, że tokeny żyją teraz w tym samym procesie co budowa envelope.
2. **`scanPathForSf` / `resolveSfExecutable`** — rezolucja where.exe (PATH-major,
   PATHEXT-minor, `.ps1` pominięte, bez cwd), potwierdzona żywo 2026-08-06;
   `shutil.which` odpada (§3).
3. **`assertPlainCliArgument`** — fail-closed strażnik quotingu (odrzuca `"`,
   znaki kontrolne) — dziś nic nie odrzuca i właśnie po to istnieje.
4. **Regexy tożsamości**: `NON_PRODUCTION_HOST`, `DEV_EDITION_HOST`, `ORG_ID`,
   `OBJECT_API_NAME`, `ALIAS` — przenoszone znak w znak (komentarz w `.mjs`
   dokumentuje semantykę isSandbox-vs-nonProduction dla Developer Edition).
5. **Kanoniczny digest envelope** — sha256 po JSON z sortowanymi kluczami i
   separatorami zwartymi, **bajt w bajt zgodny** z `canonical_bytes()` w
   `salesforce_review_client.py` (inaczej walidacja digestu odrzuci każdy envelope;
   w Pythonie to wprost ta sama funkcja — użyć jej, nie pisać drugiej).
6. **Pinowanie profili zapytań** — startowa odmowa `QUERY_PROFILE_DENIED`, gdy
   policy nie zgadza się z oczekiwanymi zapytaniami verbatim (EXPECTED_QUERIES),
   w tym komentarz-wiedza „IsUnique/IsCreatable/IsUpdatable nie istnieją na
   FieldDefinition — zweryfikowano żywo 2026-08-05".
7. **Limity bajtowe** — `MAX_OUTER_MESSAGE_BYTES` 1 MiB i cap wyniku poniżej połowy
   (envelope jest osadzany dwa razy: `content[0].text` + `structuredContent`).

## 7. Testy ukończenia (mierzalne bez baseline'u)

1. **Latencja:** 12 kolejnych `review_soql_query` w jednej sesji serwera na wolnym
   orgu — każdy call kończy się < 15 s, zero `MCP_TIMEOUT` po stronie klienta.
2. [W] **Liczba procesów:** stderr z całej powyższej sesji pokazuje **≤ 4 wywołania
   `sf`** (wersja CLI + token + display na starcie, plus ewentualny jeden refresh po
   401) i zero innych procesów potomnych.
3. [W] **Kontrakt:** `entry-org-attach` przechodzi end-to-end na envelope v2 (walidacja
   schematem + digest) przy **pustym diffie `knowledge_store.py`**; diff
   `salesforce_review_client.py` ogranicza się do linii startu procesu (nic w logice
   walidacji envelope).
4. [W] **Windows framing + refresh:** test jednostkowy z wymuszonym trybem binarnym
   potwierdza brak `\r` w każdej ramce; test 401-replay potwierdza żywą sondę
   tożsamości po refresh, **wraz z wariantem negatywnym**: mock zwracający po
   refresh inny org id ⇒ serwer przechodzi w fail-closed i każdy kolejny call
   zwraca `IDENTITY_ORG_ID_MISMATCH` (alias przepięty / nieświeży auth file nie
   może po cichu przekierować sesji na inny org).
4a. [W] **Współbieżność:** dwa `tools/call` wysłane jednocześnie (mock HTTP z ~5 s
   opóźnienia każdy) — oba dostają poprawne odpowiedzi dopasowane po id, każda ramka
   to jedna nieprzeplatana linia; przebieg wsadowy klienta (bez `initialized`, EOF)
   zwraca obie odpowiedzi i czysty exit 0.
5. **Ściana non-production:** test negatywny — host produkcyjny / org id z denied-list
   w danych startowych ⇒ serwer odmawia startu (loud fail), nie startuje w trybie
   „ostrzeżenie".
6. **Czystość:** `grep -r "@salesforce/mcp"` poza lockfile/history — 0 trafień;
   `grep -r "salesforce-review"` w ścieżkach cache — 0 trafień; pełny gate zielony.
7. **Read-only pin:** test kontraktowy wylicza powierzchnię narzędzi nowego serwera
   i pinuje ją (dokładnie 7 nazw z §3, żadnych handlerów zapisu).
8. [W] **Brama sensitive-material:** test jednostkowy — envelope narzędzia innego niż
   `review_soql_query` z podstawioną wartością o kształcie sekretu (np. `Bearer x`,
   `force://…`, org id `00D…`) wychodzi jako BLOCKED z `SENSITIVE_OUTPUT_DETECTED`;
   ten sam payload w `review_soql_query` przechodzi (zwolnienie ownera 2026-08-04).
9. **`explain_query` (żywo, bez baseline'u):** zapytanie znane-selektywne (filtr po
   `Id` lub polu indeksowanym) zwraca plan z `leadingOperationType` równym `index`
   (porównanie case-insensitive — API zwraca `Index`); zapytanie znane-nieselektywne
   (bez filtra albo filtr po polu nieindeksowanym na dużym obiekcie) zwraca
   `relativeCost > 1` **lub** `leadingOperationType` równe `tablescan`. Oba warunki
   są progami absolutnymi — nie wymagają porównania przed/po.
