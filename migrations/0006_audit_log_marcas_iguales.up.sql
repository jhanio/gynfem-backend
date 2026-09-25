-- 0006 — Corrección de la autorrevisión de PR #8 sobre audit_log.
--
-- 0005 ya está aplicada en Supabase: su archivo no se edita (el runner lo
-- rechazaría por su checksum). La corrección va en esta migración.
--
-- La hora de un registro de auditoría no la decide quien inserta: la tabla es
-- de solo inserción, así que `updated_at` debe ser siempre igual a
-- `created_at`. `created_at` sigue pudiendo fijarse en el INSERT; lo escribe
-- el backend, nunca un cliente.

ALTER TABLE gynfem.audit_log
    ADD CONSTRAINT audit_log_updated_equals_created CHECK (updated_at = created_at);
