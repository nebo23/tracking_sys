-- Run once as the database owner/administrator in pgAdmin Query Tool on tracking_sys before
-- applying migration 0005_lifecycle (D-024). It adds only the lifecycle runner's login role;
-- set its password through pgAdmin afterward and store it as TRACKING_LIFECYCLE_PASSWORD in
-- the ignored .env. Table grants come from the reviewed migration, not from this script.
-- An existing role causes a transaction failure rather than being modified.
BEGIN;

DO $$
BEGIN
    IF current_database() <> 'tracking_sys' THEN
        RAISE EXCEPTION 'Select tracking_sys before running this setup.';
    END IF;
END;
$$;

CREATE ROLE tracking_lifecycle LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
GRANT CONNECT ON DATABASE tracking_sys TO tracking_lifecycle;
GRANT USAGE ON SCHEMA public TO tracking_lifecycle;

COMMIT;
