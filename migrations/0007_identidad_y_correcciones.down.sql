-- Reversión de 0007. Si ya hay pacientes o correcciones, se pierden sus datos de
-- identidad: revertir esta migración en producción es una decisión, no un trámite.
DROP TRIGGER clinical_measurements_guard ON gynfem.clinical_measurements;
DROP TRIGGER patients_guard ON gynfem.patients;
DROP FUNCTION gynfem.forbid_undelete_and_immutable_changes();
ALTER TABLE gynfem.clinical_measurements DROP COLUMN replaces_measurement_id;
DROP INDEX gynfem.patients_active_document_idx;
ALTER TABLE gynfem.patients
    DROP CONSTRAINT patients_document_number_format,
    DROP COLUMN search_key,
    DROP COLUMN family_names,
    DROP COLUMN given_names,
    DROP COLUMN document_number,
    DROP COLUMN document_type;
