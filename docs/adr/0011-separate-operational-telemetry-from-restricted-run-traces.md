# Separate operational telemetry from restricted Run Traces

Operational telemetry carries low-sensitivity identifiers, versions, status, usage, cost, and latency, while replayable Run Traces containing evidence references or necessary payload snapshots use stricter tenant isolation, access control, and retention. Full resumes, project documents, prompts, and personal evidence are not exported to ordinary logs or third-party observability by default.
