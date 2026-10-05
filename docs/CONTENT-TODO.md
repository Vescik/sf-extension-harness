# CONTENT-TODO — pliki do uzupełnienia przez ownera (faza 2)

This owner-content backlog originated in phase 2 of the context-first plan from 2026-08-07
(archived under `docs-history-2026-08-11`). `docs/package-concept.md` and
`docs/package-constraints.md` are absent. `docs/design-guides.md` exists with limited recorded
conventions; preserve it rather than recreating it. The governed vocabulary remains in
`.ai/knowledge/keyword-taxonomy.md`; the older proposed domain document below is owner follow-up,
not an instruction to move or rewrite governed Knowledge.

Missing domain documentation does not stop a useful design draft or prove that the package has
no constraints. Use applicable instructions and permitted evidence. Name each material unknown
and the behavior or task it affects; resolve it before dependent implementation while continuing
independent work. Do not invent vendor content or team conventions. The
[Solution Design skill](../.github/skills/solution-design/SKILL.md) owns that procedure.
Filling these domain documents remains a separate owner task.

---

## 1. `docs/package-concept.md` — mapa pakietu (najważniejszy plik całego setupu)

Pytanie, na które odpowiada: **„jak działa ten świat?"** — to na nim czysty Copilot
konfabuluje, bo VendorPkg to nisza i model zmyśla obiekty z ogólnej wiedzy Salesforce.

Zacznij od frontmatteru (detektor context rot — L-1; skill solution-design porównuje
wersję z żywym `review_installed_packages`):

```yaml
---
package-version: "X.YZ" # wersja pakietu, dla której treść była pisana
last-verified: 2026-08-08 # kiedy człowiek ostatnio potwierdził prawdziwość treści
---
```

Treść — pisz jak wprowadzenie dla nowego developera w pierwszym tygodniu:

- model domenowy jako drzewko (co jest korzeniem, co dziećmi, gdzie wpinają się
  faktury/czas/finanse);
- główne obiekty z rolami: aggregate root / child / config record — z API names;
- entry points: skąd przychodzi praca, jak przepływa pieniądz/czas przez obiekty;
- co jest konfigiem, a co daną transakcyjną.

Minimum na start: **~50 linii, obszar najbliższego ticketa** — nie pisz całości od razu.
Limit docelowy ~200–300 linii; gdy obszar puchnie, wydziel go do `docs/areas/<obszar>.md`
i zostaw w koncepcie akapit + link.

## 2. `docs/package-constraints.md` — czego nie wolno / nie da się + dlaczego

Pytanie: **„co jest bugiem zanim powstanie?"** Naruszenie wpisu stąd to defekt, nie temat
do dyskusji. Ten sam frontmatter `last-verified:` co wyżej.

Format każdego wpisu — trzy elementy, zwięźle:

```markdown
- **Nie rozszerzaj obiektu X przez trigger na Y.** Upgrade pakietu nadpisuje Z i logika
  znika bez śladu. Źródło: oparzenie 2026-05-xx, ticket 2418xx / dokumentacja vendora §n.
```

Minimum na start: **10 wpisów z dotychczasowych oparzeń** (upgrade coś nadpisał,
walidacja pakietu odpaliła się nieoczekiwanie, extension point nie działał jak
w dokumentacji…). Rytuał zasilania: **każde nowe oparzenie = jeden wpis, od razu** —
wpis kosztuje edycję pliku, nie sesję.

## 3. `docs/design-guides.md` — „u nas robimy tak"

Pytanie: **„co jest tematem na review?"** (w odróżnieniu od constraints — naruszenie to
rozmowa, nie bug). Ten sam frontmatter `last-verified:`.

Sekcje do wypełnienia:

- **Nazewnictwo** — konwencje firmowe dla API names, klas, flowów (dotąd wisiały jako
  placeholder w starych instructions; wpisz realne zasady);
- **Architektura** — serwis zamiast logiki w triggerze, kiedy Flow a kiedy Apex,
  jak wersjonujemy flowy;
- **Zasady code review** — czego reviewer wymaga;
- **Format decyzji** — jak opisujemy decyzję z alternatywami w design.md;
- **Commity** (L-3 — wklej dosłownie):

```markdown
## Commity

Format: `[WI-<work-item-id>] krótki opis — AB#<work-item-id>` — np.
`[WI-242850] add notification pref flow — AB#242850`.
Commity bez work-itemu (chore, docs): `[chore]` / `[docs]`, bez `AB#`.
```

## 4. `docs/keywords-taxonomy.md` — słownik user-speak → system-speak

Pytanie: **„co user ma na myśli?"** Nie słownik ogólny — wyłącznie mapowania
rozwiązujące realne dwuznaczności Waszego języka, po jednej linii:

```markdown
- „aktywacja" → checkbox `Is_Active__c` na obiekcie X plus flow Y
- „faktura za projekt" → `VendorNS__Invoice__c` per assignment, NIE per project
```

The existing `.ai/knowledge/keyword-taxonomy.md` remains governed Knowledge. Read it through
the applicable workflow; this backlog does not authorize moving its contents or creating a
second authoritative taxonomy. Any separate domain glossary remains an owner-content decision.

---

## Po uzupełnieniu

1. Ustaw daty `last-verified:`; odświeżaj je przy przeglądzie po zamknięciu każdego
   work-itemu (nawet bez zmiany treści — data mówi „człowiek potwierdził").
2. Usuń ten plik.
3. (Opcjonalny pomiar z §7 planu) ten sam ticket dwa razy: czysty Copilot vs Copilot
   z docs — liczba zmyślonych obiektów/relacji, trafione constraints, rundy doprecyzowań.
   Wyraźna różnica → karmić dalej; brak → ograniczyć docs do constraints.
