# Separate Tool specification, execution, and policy

Each Agent tool has an independent model-visible specification, executable handler, and server-enforced policy that classifies effects, authorizes the user, requires approval, supplies idempotency, and redacts traces. Product endpoints are exposed to the model only through these policy-aware tool contracts.
