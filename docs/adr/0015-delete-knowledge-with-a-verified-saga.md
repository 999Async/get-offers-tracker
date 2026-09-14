# Delete knowledge with a verified saga

A Deletion Request immediately removes a Document Version from retrieval eligibility, then tracks deletion of Qdrant points, R2 objects, derived Candidate Facts, caches, and restricted trace payloads before reporting completion. Partial failure remains visible and retryable rather than being presented as a successful cross-store transaction.
