-- ROLLBACK for 20261104100000_create_organization_with_owner.
-- Removes the function only; organisations, memberships and audit events it created stay.
BEGIN;
DROP FUNCTION public.create_organization_with_owner(TEXT, TEXT, TEXT, TEXT);
COMMIT;
