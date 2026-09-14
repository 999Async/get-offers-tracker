import { index, integer, uniqueIndex, primaryKey, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const applications = sqliteTable(
  "applications",
  {
    userId: text("user_id").notNull(),
    id: text("id").notNull(),
    company: text("company").notNull(),
    role: text("role").notNull(),
    platform: text("platform").notNull().default(""),
    status: text("status").notNull(),
    progressHistory: text("progress_history").notNull().default("[]"),
    salary: text("salary").notNull().default(""),
    appliedAt: text("applied_at").notNull().default(""),
    note: text("note").notNull().default(""),
    resume: text("resume").notNull().default(""),
    resumeDocumentId: text("resume_document_id").notNull().default(""),
    resumeVersionId: text("resume_version_id").notNull().default(""),
    sourceJobId: text("source_job_id").notNull().default(""),
    sourceJobUrl: text("source_job_url").notNull().default(""),
    createdAt: text("created_at").notNull(),
    updatedAt: text("updated_at").notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.userId, table.id] }),
    index("applications_user_updated_idx").on(table.userId, table.updatedAt),
  ],
);

export const applicationPlanReceipts = sqliteTable("application_plan_receipts", {
  userId: text("user_id").notNull(),
  idempotencyKey: text("idempotency_key").notNull(),
  argumentsHash: text("arguments_hash").notNull(),
  planId: text("plan_id").notNull(),
  attemptId: text("attempt_id").notNull(),
  createdAt: text("created_at").notNull(),
}, (table) => [primaryKey({ columns: [table.userId, table.idempotencyKey] })]);

export const jobSources = sqliteTable("job_sources", {
  sourceId: text("source_id").primaryKey(),
  originUrl: text("origin_url").notNull(),
});

export const jobVersions = sqliteTable("job_versions", {
  versionId: text("version_id").primaryKey(),
  jobId: text("job_id").notNull(),
  sourceId: text("source_id").notNull().references(() => jobSources.sourceId),
  contentHash: text("content_hash").notNull(),
  bodyJson: text("body_json").notNull(),
}, (table) => [index("job_versions_job_idx").on(table.jobId)]);

export const jobCurrent = sqliteTable("job_current", {
  jobId: text("job_id").primaryKey(),
  versionId: text("version_id").notNull().references(() => jobVersions.versionId),
  lastSeenAt: text("last_seen_at").notNull(),
  active: integer("active").notNull().default(1),
});

export const jobIngestionRuns = sqliteTable("job_ingestion_runs", {
  ingestionId: text("ingestion_id").primaryKey(),
  startedAt: text("started_at").notNull(),
  status: text("status").notNull(),
  reportJson: text("report_json").notNull(),
});

export const jobCorpusSnapshots = sqliteTable("job_corpus_snapshots", {
  snapshotId: text("snapshot_id").primaryKey(),
  bodyJson: text("body_json").notNull(),
});

export const searchIndexVersions = sqliteTable("search_index_versions", {
  indexId: text("index_id").primaryKey(),
  snapshotId: text("snapshot_id").notNull().references(() => jobCorpusSnapshots.snapshotId),
  collectionName: text("collection_name").notNull(),
  status: text("status").notNull(),
  manifestJson: text("manifest_json").notNull(),
});

export const activeSearchIndex = sqliteTable("active_search_index", {
  alias: text("alias").primaryKey(),
  indexId: text("index_id").notNull().references(() => searchIndexVersions.indexId),
});

export const knowledgeDocuments = sqliteTable("knowledge_documents", {
  documentId: text("document_id").primaryKey(), tenantId: text("tenant_id").notNull(),
  name: text("name").notNull(), status: text("status").notNull(), activeVersion: text("active_version"),
  createdAt: text("created_at").notNull(),
}, (table) => [index("knowledge_documents_owner").on(table.tenantId)]);
export const knowledgeVersions = sqliteTable("knowledge_versions", {
  versionId: text("version_id").primaryKey(), documentId: text("document_id").notNull().references(() => knowledgeDocuments.documentId),
  sourceHash: text("source_hash").notNull(), extension: text("extension").notNull(), status: text("status").notNull(),
  sourceKey: text("source_key").notNull(), canonicalKey: text("canonical_key").notNull(), configHash: text("config_hash").notNull(),
  error: text("error"), createdAt: text("created_at").notNull(),
});
export const knowledgeEvidence = sqliteTable("knowledge_evidence", {
  evidenceId: text("evidence_id").primaryKey(), versionId: text("version_id").notNull().references(() => knowledgeVersions.versionId),
  bodyJson: text("body_json").notNull(),
}, (table) => [index("knowledge_evidence_version").on(table.versionId)]);
export const candidateFacts = sqliteTable("candidate_facts", {
  factId: text("fact_id").primaryKey(), documentId: text("document_id").notNull().references(() => knowledgeDocuments.documentId),
  versionId: text("version_id").notNull(), status: text("status").notNull(), revision: integer("revision").notNull(), bodyJson: text("body_json").notNull(),
});
export const knowledgeIndexes = sqliteTable("knowledge_indexes", {
  indexId: text("index_id").primaryKey(), tenantId: text("tenant_id").notNull(), collectionName: text("collection_name").notNull(),
  status: text("status").notNull(), manifestJson: text("manifest_json").notNull(),
});
export const knowledgeActiveIndex = sqliteTable("knowledge_active_index", {
  tenantId: text("tenant_id").primaryKey(), indexId: text("index_id").notNull(),
});
export const knowledgeDeletions = sqliteTable("knowledge_deletions", {
  documentId: text("document_id").primaryKey(), tenantId: text("tenant_id").notNull(), status: text("status").notNull(),
  stage: text("stage").notNull(), error: text("error"), updatedAt: text("updated_at").notNull(),
});

export const assistantConversations = sqliteTable("assistant_conversations", {
  userId: text("user_id").notNull(),
  id: text("id").notNull(),
  title: text("title").notNull(),
  snapshot: text("snapshot").notNull(),
  revision: integer("revision").notNull().default(1),
  updatedAt: text("updated_at").notNull(),
}, table => [primaryKey({ columns: [table.userId, table.id] }), index("assistant_conversations_user_updated_idx").on(table.userId, table.updatedAt)]);

export const radarSources = sqliteTable("radar_sources", {
  userId: text("user_id").notNull(), id: text("id").notNull(), name: text("name").notNull(), url: text("url").notNull(),
  enabled: integer("enabled").notNull().default(1), createdAt: text("created_at").notNull(),
  lastSuccess: text("last_success").notNull().default(""), lastAttempt: text("last_attempt").notNull().default(""),
  nextRun: integer("next_run").notNull(), error: text("error").notNull().default(""), count: integer("count").notNull().default(0),
  jobsJson: text("jobs_json").notNull().default("[]"), leaseToken: text("lease_token").notNull().default(""), leaseUntil: integer("lease_until").notNull().default(0),
}, table => [primaryKey({ columns: [table.userId, table.id] }), uniqueIndex("radar_sources_owner_url").on(table.userId, table.url), index("radar_sources_due").on(table.enabled, table.nextRun)]);
