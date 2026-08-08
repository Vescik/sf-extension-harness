# work-items

One folder per work item: `<id>-<slug>/` (e.g. `242850-approval-notifications/`).

- `design.md`    — what and why, written BEFORE implementation; no mandatory template
- `tasks.md`     — progress checklist; the checkboxes are the entire state
- `decisions.md` — APPEND-ONLY log of deviations and rulings made during development;
                   never edit backwards, always append

After a work item closes: review `decisions.md` — lessons promote to
`docs/package-constraints.md` or `docs/package-concept.md`; the folder stays as the
archive.
