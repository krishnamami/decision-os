"""core/infra — infrastructure adapters (SQS consumer, observability). Injectable
clients that no-op gracefully when AWS is unconfigured (the S3 / RA-P0-A pattern).
Decision-path-inert -> 16/16 by construction."""
