# Job Search and RAG

## Two retrieval problems

GetOffers has two related but distinct retrieval interfaces.

### Job Search

Job Search returns complete, ranked Job Versions. Structured fields, full-job text, matched sections, user constraints, user preferences, and freshness may contribute to the score, but multiple passages from the same job never appear as separate results.

```python
class JobSearchRequest(BaseModel):
    user_id: str
    query: str
    hard_constraints: HardConstraints
    soft_preferences: SoftPreferences
    candidate_profile_version: str
    job_corpus_version: str
    top_k: int

class JobSearchResult(BaseModel):
    jobs: list[RankedJob]
    search_config_version: str
    corpus_version: str
    trace_ref: str
```

### Knowledge Retrieval

Knowledge Retrieval returns Evidence Units from explicitly authorized scopes. It supports grounded explanations, personal-evidence selection, resume advice, and interview preparation.

```python
class EvidenceQuery(BaseModel):
    user_id: str
    query: str
    scopes: list[KnowledgeScope]
    filters: EvidenceFilters
    corpus_versions: list[str]
    top_k: int

class EvidencePack(BaseModel):
    evidence: list[Evidence]
    retrieval_config_version: str
    corpus_versions: list[str]
    trace_ref: str
```

The interfaces share retrieval infrastructure but not result semantics or evaluation labels.

## Knowledge domains

| Domain | Visibility | Primary use |
|---|---|---|
| Job corpus | Shared | Job Search and Job Evidence |
| User Knowledge Base | Private per user | User Evidence and Candidate Fact proposals |
| Candidate Facts | Private, confirmed | Hard matching and ranking features |
| Application Facts | Private, authoritative | History, status, outcomes, and planning |
| Coaching material | Shared or private by source | Later interview and career guidance |

Every retrieval call receives tenant identity from trusted server context. The model and browser cannot choose or remove the tenant filter.

## Storage layout

### D1

Suggested fact entities:

```text
documents
document_versions
evidence_units
candidate_facts
candidate_fact_evidence
job_sources
job_versions
search_index_versions
ingestion_runs
deletion_requests
application_plans
```

Each versioned entity records owner/visibility, lifecycle status, created time, source identity, active version, and relevant configuration hashes.

### R2

Content-addressed paths avoid overwriting history:

```text
tenant/{tenant_id}/documents/{document_id}/versions/{content_hash}/source.{ext}
tenant/{tenant_id}/documents/{document_id}/versions/{content_hash}/canonical.json
tenant/{tenant_id}/traces/{workflow_run_id}/{payload_hash}.json
```

### Qdrant

Initial collections:

```text
job_versions_v1
  one point = one complete Job Version

evidence_units_v1
  one point = one Evidence Unit
```

Payload includes tenant/visibility, document and version identity, evidence identity, source type, source locator, active status, content hash, parser/chunker/embedding versions, and indexed time. `tenant_id` is indexed and injected by the server adapter. Separate collections or collection versions are built before atomic activation.

## Ingestion pipeline

```text
upload or capture
→ validate type, size, ownership, and content hash
→ persist immutable Source Artifact
→ create Document Version
→ parse into Canonical Document
→ build Evidence Units
→ validate structure, locator coverage, and counts
→ generate dense and sparse representations
→ build non-active index version
→ run smoke and retrieval checks
→ activate version
→ propose Candidate Facts when relevant
```

Content is unavailable to retrieval until activation succeeds.

## Canonical Document

Parser adapters return a product-owned intermediate representation:

```python
class DocumentNode(BaseModel):
    node_id: str
    node_type: Literal["heading", "paragraph", "list_item", "table", "qa_pair"]
    text: str
    structural_path: list[str]
    parent_node_id: str | None
    order: int
    locators: list[SourceLocator]
    table_cells: list[list[str]] | None
    parser_confidence: float | None
```

- PDF/DOCX V1 adapter: Docling.
- Markdown: deterministic AST parser.
- TXT: deterministic paragraph/list/question-answer parser.
- OCR: triggered only when the text layer is absent or fails quality checks.
- Parsing Challenger: Unstructured over the same Gold Corpus.

Docling or another parser type never crosses the Knowledge interface.

## Evidence Unit policy

The initial token parameters are experiment configuration, not domain invariants:

```text
soft target: 350-500 tokens
hard max: 700-800 tokens
normal overlap: 0
oversized split overlap: 30-50 tokens
```

### Resume

- Education, work, and project entries are separate parent units.
- Responsibilities, methods, and results may be child units under the same project.
- Project name, role, and time may be added as an index prefix.
- Citations point to source text, not generated prefixes.

### Project material

- Preserve heading hierarchy and parent/child links.
- Paragraphs, lists, and tables are structural elements.
- Merge small siblings under the same heading.
- Split oversized units by list item or sentence before token windows.
- Repeat table headers when a table must be split.
- Retrieve child units and expand to parents or neighbors only when needed.

### Job descriptions

Responsibilities, requirements, bonus qualifications, location, and deadlines remain distinguishable fields and Evidence Units. A derived full-job representation is indexed for Job Search.

### Interview notes

Keep question, answer, follow-up, feedback, and revised answer together as a semantic unit. Never index an answer without the question needed to interpret it.

## Candidate Fact lifecycle

```text
proposed
→ user_confirmed
→ user_corrected
→ rejected
→ superseded
```

A proposal records claim type/value, supporting Evidence IDs, extraction configuration, and confidence. Only confirmed or corrected facts may act as Hard Constraints, primary ranking features, or statements that the user "did" something. Rejected and superseded facts remain auditable but inactive.

## Job Search pipeline

```text
trusted constraints and preferences
→ query normalization and field extraction
→ Hard Constraint filter
→ BM25 candidate retrieval
→ dense candidate retrieval
→ reciprocal rank fusion
→ feature construction
→ cross-encoder reranking
→ duplicate/diversity/freshness adjustment
→ score explanation
→ Ranked Jobs
```

Potential ranking features include responsibility match, skill coverage, matching Candidate Facts, negative-duty penalty, location, industry preference, recruitment type, source quality, freshness, prior feedback, novelty, and duplication. Initial weights are explicit configuration; learned ranking is deferred until sufficient reviewed labels exist.

The LLM does not score the whole job corpus. It receives only the small ranked candidate set for evidence synthesis and explanation.

## Knowledge Retrieval pipeline

```text
authorized scope and metadata filter
→ BM25 Evidence Unit retrieval
→ dense Evidence Unit retrieval
→ reciprocal rank fusion
→ cross-encoder reranking
→ deduplication
→ parent/neighbor expansion when justified
→ token-budgeted Evidence Pack
```

The Evidence Pack retains document, version, unit, locator, retrieval score, rerank score, and trust classification. External content is marked untrusted and cannot change Runtime policy or tool permissions.

## Baseline and Challengers

### Retrieval Baseline

```text
Qdrant BM25
+ BAAI/bge-m3 dense embeddings
+ RRF
+ BAAI/bge-reranker-v2-m3
```

BGE-M3 learned sparse and multi-vector modes are separate experiments, not silently mixed into the baseline.

### Model Challengers

- Quality Challenger: Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B.
- Efficiency Challenger: gte-multilingual-base and gte-multilingual-reranker-base.

Each experiment changes one factor when possible. Query instructions, tokenizer, vector dimension, normalization, truncation, and model revision are versioned. Public benchmark rankings do not substitute for GetOffers evaluation.

### Search-engine Challenger

OpenSearch may index the same Job Versions and Evidence Units with the same labels and dense model. Compare Qdrant and OpenSearch on quality, p95, index time, storage, deletion, and operational burden; do not migrate product facts for this experiment.

## Evaluation

### Parsing Gold Corpus

Target 40-60 documents covering single/multi-column resumes, tables, scanned pages, Chinese/English mixtures, PDF/DOCX/Markdown/TXT, and damaged/encrypted/empty inputs.

Measure content preservation, reading order, structure classification, parent relationships, table quality, locator coverage, determinism, success/failure categories, per-page latency, peak memory, and OCR ratio.

### Job Search evaluation

Target about 150 reviewed queries with 0-3 relevance labels, Hard Constraints, excluded conditions, and relevant Job Version IDs.

Measure Recall@20/50/100, Precision@K, MRR, nDCG@5/10, Hard Constraint violations, stale/duplicate rate, diversity, p50/p95, and index cost.

### Evidence Retrieval evaluation

Target about 100 reviewed questions with expected Evidence Unit IDs, required facts, forbidden claims, and citation locators.

Measure Recall@K, MRR, nDCG, citation hit/precision, parent-expansion gain, cross-section contamination, repeated-token ratio, latency, and retrieval cost.

## Deletion and reindexing

Deletion is a stateful saga:

```text
mark deleting and remove retrieval eligibility
→ delete Qdrant points and verify zero matches
→ delete explicit R2 object keys
→ remove derived Candidate Facts, caches, and restricted trace content
→ verify all stores
→ mark deleted
```

Failure remains `deleting` and retryable. Every index build stores a manifest of exact document/vector identities. Reindexing builds a new collection or index version, validates it on frozen data, atomically changes the active version, preserves a bounded rollback window, and then removes the old index.

## Primary references

- [Qdrant hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/)
- [Qdrant full-text and BM25](https://qdrant.tech/documentation/search/text-search/full-text-search/)
- [Docling document model](https://docling-project.github.io/docling/concepts/docling_document/)
- [Docling chunking](https://docling-project.github.io/docling/concepts/chunking/)
- [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)
- [BGE reranker model card](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [Qwen3 Embedding model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Qwen3 Reranker model card](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)
