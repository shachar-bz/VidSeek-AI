-- The extensions every later migration depends on.
--
-- Alone in its own file because these are the two statements that can fail for a reason
-- that has nothing to do with the schema: an extension has to be permitted by the server
-- before any role may create it. Keeping them apart means a failure here points at the
-- server's configuration rather than at whichever table happened to be first.
--
-- Applied by `python -m backend.storage.postgres.migrate`, which runs each file once, in
-- filename order, inside its own transaction. Re-running is safe: every statement below
-- is idempotent.

-- `gen_random_uuid()`, the default of every generated primary key that follows. Built in
-- since Postgres 13, but created explicitly so this file states what it relies on rather
-- than assuming a version.
create extension if not exists pgcrypto;

-- pgvector, for the embedding columns in 0007. Enabled here rather than in that migration
-- because enabling an extension is a one-off server-level step, and having it in place
-- costs nothing until something uses it.
--
-- On Azure Database for PostgreSQL Flexible Server this statement fails until `vector` is
-- added to the `azure.extensions` server parameter: Portal > the server > Settings >
-- Server parameters > search `azure.extensions` > tick VECTOR > Save. No role, not even
-- the administrator, may create an extension the server has not been told to allow.
create extension if not exists vector;
