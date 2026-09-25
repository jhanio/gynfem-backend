-- 0002 — Pacientes gestantes: solo columnas estructurales.
--
-- Los datos de identidad (HU003) están PENDIENTES de definir por el producto y
-- los añade la Fase 10: nadie escribe en esta tabla antes, así que añadirlos
-- no requiere migrar datos. `created_by`, `updated_by` y `deleted_by` apuntarán
-- a los usuarios de la Fase 11; hoy son nulos y no tienen clave foránea.

CREATE TABLE gynfem.patients (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz,
    created_by  uuid,
    updated_by  uuid,
    deleted_by  uuid
);
ALTER TABLE gynfem.patients ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE gynfem.patients FROM PUBLIC, anon, authenticated;

CREATE TRIGGER patients_set_updated_at BEFORE UPDATE ON gynfem.patients
    FOR EACH ROW EXECUTE FUNCTION gynfem.set_updated_at();
CREATE TRIGGER patients_forbid_delete BEFORE DELETE ON gynfem.patients
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_physical_delete();
CREATE TRIGGER patients_forbid_truncate BEFORE TRUNCATE ON gynfem.patients
    FOR EACH STATEMENT EXECUTE FUNCTION gynfem.forbid_physical_delete();

COMMENT ON TABLE gynfem.patients IS 'Paciente gestante. Identidad: PENDIENTE (Fase 10).';
