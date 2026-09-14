CREATE TABLE `application_plan_receipts` (
	`user_id` text NOT NULL,
	`idempotency_key` text NOT NULL,
	`arguments_hash` text NOT NULL,
	`plan_id` text NOT NULL,
	`attempt_id` text NOT NULL,
	`created_at` text NOT NULL,
	PRIMARY KEY(`user_id`, `idempotency_key`)
);
