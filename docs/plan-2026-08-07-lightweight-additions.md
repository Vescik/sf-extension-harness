# Plan — lightweight additions do architektury context-first

Data: 2026-08-07
Status: **plan do realizacji, bez implementacji.** Nic z tego nie zostało jeszcze wykonane.
Autor zapisu: Claude (chat), na podstawie rozmowy z ownerem
Dokument nadrzędny: `plan-2026-08-07-context-first-architecture.md` — ten plan go rozszerza,
niczego nie zmienia. Kryterium doboru identyczne: **treść albo obserwacja, zero procesu.**
Wszystkie pozycje przyjęte przez ownera; łączny koszt ~pół dnia + szkic skilla.

---

## 1. Zakres — sześć pozycji

| # | Pozycja | Koszt | Kategoria |
|---|---|---|---|
| L-1 | Stempel wersji pakietu w `docs/package-concept.md` | 1 linia + 1 zdanie skilla | detektor context rot |
| L-2 | PR template z checkboxem namespace | 1 plik | review-time guard |
| L-3 | Konwencja commitów `[<work-item-id>] opis` | 1 zdanie w design-guides | traceability |
| L-4 | `work-items/README.md` | ~10 linii | trwałość konwencji |
| L-5 | `Last verified:` w nagłówkach docs/ | 1 linia per plik + rytuał | świeżość treści |
| L-6 | `git-workflow/SKILL.md` + `git-agent.md` | ~pół dnia | wyrównanie wiedzy git |

(Numeracja L-* — lightweight; odróżnia od C-* z planu nadrzędnego.)

---

## 2. L-1 — stempel wersji pakietu (najtańszy detektor context rot)

Frontmatter `docs/package-concept.md`:

```yaml
package-version: "1.86"        # wersja, dla której treść była pisana
last-verified: 2026-08-07
```

Do `solution-design/SKILL.md` jedno zdanie: „Porównaj `package-version` z wynikiem
`review_installed_packages`; przy rozjeździe dopisz do designu ostrzeżenie
»docs opisują X, org ma Y« i traktuj różnice z ostrożnością."

Efekt: mitygacja „mapa vs teren" z §5 planu nadrzędnego dostaje mechaniczny trigger
zamiast liczyć na czujność modelu.

## 3. L-2 — PR template z jednym checkboxem

`.github/pull_request_template.md`:

```markdown
## Work item
[242850] <tytuł>  ·  link do work-items/<folder>/

## Zmiany w namespace paczki
- [ ] Brak zmian dotykających namespace `VendorNS__`
- [ ] Wypisane w design.md z dowodem z orga (kontrakt obiektu / installed packages)

## Checklist
- [ ] decisions.md uzupełnione o odstępstwa od designu (albo brak odstępstw)
```

Efekt: review-time'owy odpowiednik nieistniejącego `check_package_boundary.py` — niczego
nie wymusza u agenta, ale gwarantuje, że owner przy merge zawsze widzi to pytanie.
Reguła graniczna dostaje czwarty punkt styku (po copilot-instructions,
managed-package.instructions i designer-agencie).

## 4. L-3 — konwencja commitów

Do `docs/design-guides.md`:

```markdown
## Commity
Format: `[<work-item-id>] krótki opis` — np. `[242850] add notification pref flow`.
Commity bez work-itemu (chore, docs): `[chore]` / `[docs]`.
```

Efekt: `git log --grep '\[242850\]'` = pełna traceability implementacji work-itemu.
To jest cała funkcja, którą dawny work_record realizował tysiącami linii — za darmo.
Konwencja egzekwowana przez git-workflow skill (L-6), nie przez walidator.

## 5. L-4 — `work-items/README.md`

```markdown
# work-items

Jeden folder per work item: `<id>-<slug>/` (np. `242850-approval-notifications/`).

- design.md    — co i dlaczego, PRZED implementacją; bez wymuszonego szablonu
- tasks.md     — checklista postępu; checkboxy są całym stanem
- decisions.md — APPEND-ONLY log odstępstw i rozstrzygnięć w trakcie developmentu;
                 nie edytuj wstecz, dopisuj na końcu

Po zamknięciu work-itemu: przejrzyj decisions.md — wnioski awansują do
docs/package-constraints.md albo docs/package-concept.md; folder zostaje jako archiwum.
```

Efekt: konwencja żyje tam, gdzie powstaje pokusa odstępstwa (czwarty plik, edycja
decisions wstecz). README w folderze przeżywa rotację pamięci ludzi i agentów.

## 6. L-5 — `Last verified:` w nagłówkach docs/

Każdy plik w `docs/` dostaje w nagłówku `Last verified: <data>` — **nie** „last modified"
(to daje git), tylko „kiedy człowiek ostatnio potwierdził, że treść jest prawdziwa".

Rytuał (dopisany do §5 planu nadrzędnego jako rozszerzenie istniejącego): przegląd po
zamknięciu US aktualizuje datę nawet bez zmian treści. Po roku od razu widać — owner
i agent — które pliki są świeże, a których nikt nie potwierdził od dwóch upgrade'ów.

## 7. L-6 — git-workflow skill + git-agent

Uzasadnienie: git to domena, w której wiedza proceduralna („jak MY to robimy") jest
ważniejsza niż inteligencja, a rozrzut wiedzy między devami realnie produkuje bałagan
w historii. Konstrukcja: **gruby skill + cienki agent** — wartość mieszka w skillu,
agent jest wygodą.

### 7.1 `git-workflow/SKILL.md` — jedno źródło prawdy o konwencjach

Zawartość:
- nazewnictwo branchy: `feature/<id>-<slug>`, `fix/<id>-<slug>`, `chore/<opis>`;
- format commitów wg L-3 (skill jest miejscem egzekwowania konwencji);
- przepis na PR: branch aktualny względem main, historia uporządkowana, template L-2
  wypełniony, link do work-itemu;
- konflikt merge: **stop i pokaż człowiekowi — nigdy nie rozwiązuj po cichu**;
- kiedy squash (feature z chaotyczną historią lokalną), kiedy nie (historia niesie
  informację per krok);
- jak wygląda czysta historia przed review (commity logiczne, nie „wip", „fix", „fix2").

Skill jest **współdzielony**: ładuje go git-agent ORAZ developer-agent — konwencje
obowiązują niezależnie od tego, kto wykonuje operację.

### 7.2 `git-agent.md` — cienki wrapper (~25 linii)

Rola: „Wykonuję rutynowe operacje git wg git-workflow skilla: przygotuj branch dla
work-itemu, zrób commit w poprawnym formacie, uporządkuj lokalną historię przed review,
przygotuj PR z wypełnionym template'em." Sens istnienia: dev słabo znający gita mówi
„przygotuj mi PR z tego, co mam" — i dostaje wynik zgodny z konwencją zespołu, nie ze
swoją wersją wiedzy o gicie.

Granice (git-agent to miejsce koncentracji operacji nieodwracalnych):

| Kategoria | Operacje |
|---|---|
| **nigdy** | force-push w każdej postaci; rewrite historii na branchu współdzielonym; usuwanie branchy zdalnych; `reset --hard` |
| **zawsze pyta przed** | merge do main; push czegokolwiek; operacje na cudzych commitach |
| **swobodnie** | lokalne commity; branch; stash; status/log/diff; przygotowanie opisu PR |

Do sprawdzenia przy implementacji: pokrycie deny-listy safety hooka — `reset --hard` już
łapie; **dopiąć `push --force*` / `push -f`** jako naturalną pozycję obok istniejących
wzorców destrukcyjnych (jedna linia w hooku — jedyny kod tego planu).

### 7.3 Granica zakresu — zapisana z premedytacją

Git-agent **nie rośnie** w release managera: wersjonowanie, changelogi, tagowanie,
deployment to decyzje człowieka, poza zakresem agenta. To jest dokładnie ścieżka rozrostu,
którą przeszedł solution-design runtime — rutynowe operacje wg skilla, koniec zakresu.
Rozszerzenie zakresu wymaga jawnej decyzji ownera.

---

## 8. Jak to się spina w całość

Cztery pozycje L-1…L-5 + L-6 składają się w komplet bez polegania na pamięci devów:
konwencja commitów żyje w skillu (L-6 egzekwuje L-3), PR template (L-2) jest przez
git-agenta wypełniany, README (L-4) mówi, dokąd linkuje PR, stemple (L-1, L-5) pilnują
świeżości treści, którą reszta architektury konsumuje. Zero nowych mechanizmów
wykonawczych; jedyny kod to jedna linia w istniejącym safety hooku (§7.2).

## 9. Kolejność wdrożenia

| Krok | Co | Koszt |
|---|---|---|
| 1 | L-2, L-3, L-4, L-5 + L-1 frontmatter | ~1 h, czysta treść |
| 2 | L-6: git-workflow/SKILL.md | ~2 h (najwięcej treści decyzyjnej: squash policy, branch naming — decyzje ownera) |
| 3 | L-6: git-agent.md + linia `push --force*` w safety hooku + zdanie L-1 w solution-design skillu | ~1 h |
| 4 | piny `validate_harness.py` (nowy skill i agent zmieniają liczności) | ~15 min |

Wdrażać razem z krokami 1–3 planu nadrzędnego albo tuż po — L-6 nie ma zależności
i może iść równolegle.

Mapowanie na fazy planu nadrzędnego (§6 tamże): krok 1 wchodzi do **fazy 2** (L-1, L-5 —
stemple w docs/ przy ich tworzeniu; L-3 — sekcja w design-guides) i **fazy 3** (L-2 —
PR template; L-4 — README przy tworzeniu struktury work-items); kroki 2–3 (L-6) idą
równolegle z fazą 3; krok 4 dokleja się do **fazy 6** (jedna aktualizacja pinów dla
wszystkiego naraz). Linia `push --force*` w safety hooku to jedyny wyjątek od reguły
„hooki bez zmian" z planu nadrzędnego — rozszerzenie deny-listy, nie zmiana zachowania.

## 10. Świadomie niedodane (odrzucone przy selekcji)

- walidatory linków/struktury docs w CI — pierwszy krok z powrotem do walidowania treści
  maszyną;
- szablon design.md, nawet „opcjonalny" — opcjonalny szablon w repo staje się obowiązkowy
  w praktyce (model go znajdzie i potraktuje jak formularz);
- auto-generowanie docs z orga — docs mają być tym, co człowiek stwierdził, nie zrzutem;
  inaczej tracą jedyną przewagę nad wywołaniem MCP;
- release-management w git-agencie — §7.3.
