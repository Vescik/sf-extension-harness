## Work item

[<id>] <title>  ·  link: `work-items/<id>-<slug>/`

## Package namespace changes

- [ ] No changes touching the `VendorNS__` namespace
- [ ] Called out in `design.md` with org evidence (object contract / installed packages)

## Checklist

- [ ] `decisions.md` updated with deviations from the design (or states there were none)
- [ ] Tests written and passing for the changed Apex/Flows
- [ ] No credential, customer data, cache, or local config included

## Harness changes only

When the PR touches agents, prompts, skills, instructions, hooks, or scripts:

- [ ] `python3 scripts/validate_harness.py`
- [ ] `python3 -m unittest discover -s tests`
- [ ] `python3 scripts/run_evals.py`
