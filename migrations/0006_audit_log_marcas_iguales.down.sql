-- Reversión de 0006.
ALTER TABLE gynfem.audit_log DROP CONSTRAINT audit_log_updated_equals_created;
