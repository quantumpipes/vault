# PostgreSQL Tuning

Connection pooling is handled by pgbouncer in transaction mode. shared_buffers is set to roughly 25 percent of system memory. Autovacuum thresholds are lowered on high-write tables to avoid bloat.
