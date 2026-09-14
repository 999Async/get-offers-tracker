# Runtime contract evaluation v1

`cases.json` contains nine **synthetic runtime contract cases**, not human-reviewed career relevance labels:

- A read-only completion.
- A granted Application Plan.
- A rejected Application Plan.
- A pending approval with zero writes.
- An unknown tool.
- A write hidden by the current workflow stage.
- An injected tenant argument.
- A missing capability.
- A malformed write argument.

`baseline.json` permits eight Steps. `challenger-short-budget.json` permits only two and deliberately fails the approved-plan outcome: it can write the approved plan but cannot generate the final summary. This is a negative control for the gate, not a release candidate.

The report pins the complete dataset content hash, config, model scripts, workflow/tool fingerprints, runtime source hash, grader version, and synthetic corpus/user-state/pricing identities. UUIDs and timings vary; deterministic scores, usage, and pairing identities should not. Changing cases requires a new dataset version for published comparisons.

Run from the repository root with `npm run agent:eval`. Additional approval, crash recovery, budget, cancellation, privacy and Event Store boundaries are exercised by `npm run agent:test`. Tests and synthetic evaluation are prerequisites for later human-reviewed Job Search/Core/Edge/Lockbox datasets; they do not replace them.
