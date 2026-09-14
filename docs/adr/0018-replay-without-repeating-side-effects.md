# Replay without repeating side effects

Replay rebuilds state and reruns evaluation from recorded events and payloads without calling models, tools, or external systems again. A deliberate re-execution creates a new linked Workflow Run, and resumable write tools use approval-bound idempotency keys so retries cannot duplicate Application Plans or external actions.
