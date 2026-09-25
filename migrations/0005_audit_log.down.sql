-- Reversión de 0005. Índices, triggers y la secuencia de identidad se eliminan con la tabla.
DROP TABLE gynfem.audit_log;
DROP FUNCTION gynfem.forbid_audit_update();
