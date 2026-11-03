-- Per-database Supabase stand-in for LOCAL replay tests (run as supabase_admin).
CREATE SCHEMA extensions;
CREATE EXTENSION postgis WITH SCHEMA extensions;
GRANT USAGE ON SCHEMA extensions TO postgres WITH GRANT OPTION;
GRANT USAGE ON SCHEMA extensions TO anon, authenticated, service_role;
ALTER SCHEMA public OWNER TO postgres;
CREATE SCHEMA auth AUTHORIZATION supabase_auth_admin;
SET ROLE supabase_auth_admin;
CREATE TABLE auth.users (id UUID PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS UUID LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
GRANT USAGE ON SCHEMA auth TO postgres, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION auth.uid() TO postgres, anon, authenticated, service_role;
GRANT SELECT, REFERENCES ON auth.users TO postgres;
GRANT SELECT ON auth.users TO service_role;
RESET ROLE;
