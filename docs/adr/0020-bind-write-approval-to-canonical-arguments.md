# Bind write approval to canonical arguments

A write approval identifies the user, tool, normalized arguments, argument hash, expiration, reason, and idempotency key. Execution is authorized only for that exact payload; any material argument change invalidates the approval and requires a new user confirmation.
