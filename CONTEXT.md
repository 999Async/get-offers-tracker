# GetOffers Career Intelligence

GetOffers helps a job seeker discover suitable jobs, ground career advice in personal evidence, and track decisions and application outcomes.

## Language

**Job Search**:
Retrieval and ranking over the shared job corpus using job attributes, job text, user constraints, and user preferences. It returns ranked jobs rather than generated answers.
_Avoid_: Job RAG, vector search

**Job Evidence**:
A versioned passage from a job source that supports a claim about the job, such as a responsibility, requirement, location, or deadline.
_Avoid_: Job chunk, context

**Ranked Job**:
A complete job entity returned by Job Search with its rank, score breakdown, and source version. It is never an individual passage from a job description.
_Avoid_: Search chunk, job result

**Hard Constraint**:
A user requirement whose violation makes a job ineligible or makes an action unsafe to execute.
_Avoid_: Preference, ranking weight

**Soft Preference**:
A user preference that changes ranking but does not make a job ineligible when it is unmet.
_Avoid_: Requirement, hard filter

**User Knowledge Base**:
A private, user-owned collection of uploaded resumes, project materials, interview notes, and other career documents.
_Avoid_: Resume store, personal RAG

**Source Artifact**:
The immutable file or captured source submitted for knowledge ingestion, retained with ownership, provenance, and content identity.
_Avoid_: Upload, knowledge file

**Document Version**:
A versioned interpretation of one Source Artifact from which structured content and Evidence Units are derived.
_Avoid_: Parsed file, latest document

**Canonical Document**:
A parser-independent structural representation of a Document Version that preserves reading order, hierarchy, tables, and source locators.
_Avoid_: Docling document, parsed Markdown

**Deletion Request**:
A user-authorized operation that makes private knowledge unavailable immediately and tracks removal of every derived copy until verified complete.
_Avoid_: Delete flag, cleanup job

**User Evidence**:
A passage or verified fact from the User Knowledge Base that supports a claim about the user's experience, preference, or qualification.
_Avoid_: Profile context, memory

**Candidate Fact**:
A structured statement about the user that is traceable to User Evidence and has been confirmed by the user when its accuracy affects matching or advice.
_Avoid_: Extracted profile, inferred skill

**Knowledge Retrieval**:
Evidence retrieval from explicitly selected knowledge scopes. It returns Job Evidence or User Evidence for grounded reasoning and answers.
_Avoid_: Job Search, universal RAG

**Evidence Unit**:
The smallest independently retrievable and citable part of a versioned source, shaped by the source document's semantic structure and carrying a stable source locator.
_Avoid_: Chunk, text block

**Run Trace**:
The replayable history of one career workflow, including decisions, retrieved evidence, tool activity, approvals, resource usage, and outcomes.
_Avoid_: Log, chat history

**Decision Explanation**:
A user-visible account of why a result was produced, supported by permitted evidence and score factors without exposing internal Run Trace data or hidden model reasoning.
_Avoid_: Trace, chain of thought

**Developer Operator**:
An authorized maintainer who can inspect redacted operational traces, run evaluations, and manage experiments without receiving unrestricted access to private user content.
_Avoid_: Admin, all-access user

**Career Workflow**:
A bounded user-requested process that pursues one career outcome, such as discovering suitable jobs or preparing for an interview.
_Avoid_: Chat, Agent session

**Job Discovery**:
A Career Workflow that interprets user intent, applies Hard Constraints, ranks complete jobs, and explains the result with Job Evidence and User Evidence.
_Avoid_: Job RAG, job listing

**Workflow Outcome**:
The terminal business result of a Career Workflow, including success, partial completion, rejection, cancellation, or failure and its supporting evidence.
_Avoid_: Final answer, last message

**Feedback Signal**:
An observed user action or application outcome that may indicate usefulness but is not, by itself, a relevance label or proof of recommendation quality.
_Avoid_: Ground truth, reward

**Evaluation Case**:
A versioned task input with expected constraints, relevance or evidence labels, and scoring criteria used to compare system configurations.
_Avoid_: Example, test prompt

**Career Agent**:
The decision-making actor that combines ranked jobs, retrieved evidence, user intent, and approved tools to perform a career task.
_Avoid_: Chatbot, recommender

**Application Plan**:
A user-confirmed intention to apply for a specific job. It is distinct from an Application Record, which means an application was actually submitted.
_Avoid_: Pending application, application

**Application Autofill**:
A user-initiated browser action that fills supported recruitment-form fields for review without autonomously submitting an application.
_Avoid_: Auto-apply, autonomous application
