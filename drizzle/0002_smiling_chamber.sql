CREATE TABLE `candidate_facts` (
	`fact_id` text PRIMARY KEY NOT NULL,
	`document_id` text NOT NULL,
	`version_id` text NOT NULL,
	`status` text NOT NULL,
	`revision` integer NOT NULL,
	`body_json` text NOT NULL,
	FOREIGN KEY (`document_id`) REFERENCES `knowledge_documents`(`document_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `knowledge_active_index` (
	`tenant_id` text PRIMARY KEY NOT NULL,
	`index_id` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `knowledge_deletions` (
	`document_id` text PRIMARY KEY NOT NULL,
	`tenant_id` text NOT NULL,
	`status` text NOT NULL,
	`stage` text NOT NULL,
	`error` text,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `knowledge_documents` (
	`document_id` text PRIMARY KEY NOT NULL,
	`tenant_id` text NOT NULL,
	`name` text NOT NULL,
	`status` text NOT NULL,
	`active_version` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `knowledge_documents_owner` ON `knowledge_documents` (`tenant_id`);--> statement-breakpoint
CREATE TABLE `knowledge_evidence` (
	`evidence_id` text PRIMARY KEY NOT NULL,
	`version_id` text NOT NULL,
	`body_json` text NOT NULL,
	FOREIGN KEY (`version_id`) REFERENCES `knowledge_versions`(`version_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `knowledge_evidence_version` ON `knowledge_evidence` (`version_id`);--> statement-breakpoint
CREATE TABLE `knowledge_indexes` (
	`index_id` text PRIMARY KEY NOT NULL,
	`tenant_id` text NOT NULL,
	`collection_name` text NOT NULL,
	`status` text NOT NULL,
	`manifest_json` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `knowledge_versions` (
	`version_id` text PRIMARY KEY NOT NULL,
	`document_id` text NOT NULL,
	`source_hash` text NOT NULL,
	`extension` text NOT NULL,
	`status` text NOT NULL,
	`source_key` text NOT NULL,
	`canonical_key` text NOT NULL,
	`config_hash` text NOT NULL,
	`error` text,
	`created_at` text NOT NULL,
	FOREIGN KEY (`document_id`) REFERENCES `knowledge_documents`(`document_id`) ON UPDATE no action ON DELETE no action
);
