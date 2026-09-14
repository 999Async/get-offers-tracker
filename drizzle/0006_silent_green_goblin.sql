CREATE TABLE `radar_sources` (
	`user_id` text NOT NULL,
	`id` text NOT NULL,
	`name` text NOT NULL,
	`url` text NOT NULL,
	`enabled` integer DEFAULT 1 NOT NULL,
	`created_at` text NOT NULL,
	`last_success` text DEFAULT '' NOT NULL,
	`last_attempt` text DEFAULT '' NOT NULL,
	`next_run` integer NOT NULL,
	`error` text DEFAULT '' NOT NULL,
	`count` integer DEFAULT 0 NOT NULL,
	`jobs_json` text DEFAULT '[]' NOT NULL,
	`lease_token` text DEFAULT '' NOT NULL,
	`lease_until` integer DEFAULT 0 NOT NULL,
	PRIMARY KEY(`user_id`, `id`)
);
--> statement-breakpoint
CREATE UNIQUE INDEX `radar_sources_owner_url` ON `radar_sources` (`user_id`,`url`);--> statement-breakpoint
CREATE INDEX `radar_sources_due` ON `radar_sources` (`enabled`,`next_run`);