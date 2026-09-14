# Separate job ranking from evidence retrieval

Job Search retrieves and ranks complete job entities using structured and textual fields, while Knowledge Retrieval returns citable Evidence Units from job or user documents. Passage-level matches may contribute features to a job score, but multiple passages from one job must not compete as independent jobs in the ranked result.
