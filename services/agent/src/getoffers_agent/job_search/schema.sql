CREATE TABLE IF NOT EXISTS `active_search_index` (
	`alias` text PRIMARY KEY NOT NULL,
	`index_id` text NOT NULL,
	FOREIGN KEY (`index_id`) REFERENCES `search_index_versions`(`index_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `job_corpus_snapshots` (
	`snapshot_id` text PRIMARY KEY NOT NULL,
	`body_json` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `job_current` (
	`job_id` text PRIMARY KEY NOT NULL,
	`version_id` text NOT NULL,
	`last_seen_at` text NOT NULL,
	`active` integer DEFAULT 1 NOT NULL,
	FOREIGN KEY (`version_id`) REFERENCES `job_versions`(`version_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `job_ingestion_runs` (
	`ingestion_id` text PRIMARY KEY NOT NULL,
	`started_at` text NOT NULL,
	`status` text NOT NULL,
	`report_json` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `job_sources` (
	`source_id` text PRIMARY KEY NOT NULL,
	`origin_url` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `job_versions` (
	`version_id` text PRIMARY KEY NOT NULL,
	`job_id` text NOT NULL,
	`source_id` text NOT NULL,
	`content_hash` text NOT NULL,
	`body_json` text NOT NULL,
	FOREIGN KEY (`source_id`) REFERENCES `job_sources`(`source_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `job_versions_job_idx` ON `job_versions` (`job_id`);--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `search_index_versions` (
	`index_id` text PRIMARY KEY NOT NULL,
	`snapshot_id` text NOT NULL,
	`collection_name` text NOT NULL,
	`status` text NOT NULL,
	`manifest_json` text NOT NULL,
	FOREIGN KEY (`snapshot_id`) REFERENCES `job_corpus_snapshots`(`snapshot_id`) ON UPDATE no action ON DELETE no action
);

--> statement-breakpoint
CREATE TRIGGER IF NOT EXISTS job_versions_immutable_update BEFORE UPDATE ON job_versions
BEGIN SELECT RAISE(ABORT, 'immutable job version'); END;
--> statement-breakpoint
CREATE TRIGGER IF NOT EXISTS job_versions_immutable_delete BEFORE DELETE ON job_versions
BEGIN SELECT RAISE(ABORT, 'immutable job version'); END;
--> statement-breakpoint
CREATE TRIGGER IF NOT EXISTS job_corpus_immutable_update BEFORE UPDATE ON job_corpus_snapshots
BEGIN SELECT RAISE(ABORT, 'immutable corpus snapshot'); END;
