# Store facts in D1, artifacts in R2, and indexes in Qdrant

D1 owns document versions, permissions, Candidate Facts, Evidence Unit metadata, workflow state, and application facts; R2 stores content-addressed immutable Source Artifacts and derived files; Qdrant stores versioned dense and sparse representations that can be rebuilt from D1 and R2. OpenSearch may be evaluated as a retrieval Challenger but does not own product facts.
