CREATE TABLE `applications` (
	`user_id` text NOT NULL,
	`id` text NOT NULL,
	`company` text NOT NULL,
	`role` text NOT NULL,
	`platform` text DEFAULT '' NOT NULL,
	`status` text NOT NULL,
	`progress_history` text DEFAULT '[]' NOT NULL,
	`salary` text DEFAULT '' NOT NULL,
	`applied_at` text DEFAULT '' NOT NULL,
	`note` text DEFAULT '' NOT NULL,
	`resume` text DEFAULT '' NOT NULL,
	`source_job_id` text DEFAULT '' NOT NULL,
	`source_job_url` text DEFAULT '' NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	PRIMARY KEY(`user_id`, `id`)
);
--> statement-breakpoint
CREATE INDEX `applications_user_updated_idx` ON `applications` (`user_id`,`updated_at`);