-- Run as the database owner/administrator in pgAdmin Query Tool on tracking_sys.
-- Provision dedicated roles once; passwords are set through pgAdmin afterward.
-- Existing roles cause a transaction failure rather than being modified.
BEGIN;

DO $$
BEGIN
    IF current_database() <> 'tracking_sys' THEN
        RAISE EXCEPTION 'Select tracking_sys before running this setup.';
    END IF;
    IF current_setting('server_version_num')::integer / 10000 <> 18 THEN
        RAISE EXCEPTION 'This project requires PostgreSQL 18.';
    END IF;
END;
$$;

CREATE ROLE tracking_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tracking_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE tracking_sys TO tracking_migrator, tracking_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO tracking_migrator;
GRANT USAGE ON SCHEMA public TO tracking_app;

COMMIT;
