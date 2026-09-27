-- Reversión de 0008. Se pierden los perfiles (rol y estado): las cuentas siguen
-- en Supabase Auth, pero nadie podrá operar hasta volver a aplicarla y crear el
-- primer administrador (docs/DEPLOYMENT.md). Revertirla en producción es una
-- decisión, no un trámite.
DROP POLICY schema_migrations_deny_data_api ON gynfem_migrations.schema_migrations;
DROP POLICY user_profiles_deny_data_api ON gynfem.user_profiles;
DROP POLICY audit_log_deny_data_api ON gynfem.audit_log;
DROP POLICY predictions_deny_data_api ON gynfem.predictions;
DROP POLICY clinical_measurements_deny_data_api ON gynfem.clinical_measurements;
DROP POLICY patients_deny_data_api ON gynfem.patients;

-- La auditoría es de solo inserción: si ya registró la gestión de usuarios, esas
-- filas no se pueden borrar ni exigirles la restricción anterior. Entonces se
-- restaura `NOT VALID`: rige para toda fila nueva y respeta las existentes. Sin
-- esas filas, el catálogo queda exactamente como antes de la 0008.
ALTER TABLE gynfem.audit_log DROP CONSTRAINT audit_log_entity_type_valid;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM gynfem.audit_log WHERE entity_type = 'user') THEN
        ALTER TABLE gynfem.audit_log ADD CONSTRAINT audit_log_entity_type_valid
            CHECK (entity_type IN ('patient', 'clinical_measurement', 'prediction')) NOT VALID;
    ELSE
        ALTER TABLE gynfem.audit_log ADD CONSTRAINT audit_log_entity_type_valid
            CHECK (entity_type IN ('patient', 'clinical_measurement', 'prediction'));
    END IF;
END;
$$;

ALTER TABLE gynfem.audit_log DROP CONSTRAINT audit_log_actor_user_id_fkey;
ALTER TABLE gynfem.predictions
    DROP CONSTRAINT predictions_created_by_fkey,
    DROP CONSTRAINT predictions_updated_by_fkey,
    DROP CONSTRAINT predictions_deleted_by_fkey;
ALTER TABLE gynfem.clinical_measurements
    DROP CONSTRAINT clinical_measurements_created_by_fkey,
    DROP CONSTRAINT clinical_measurements_updated_by_fkey,
    DROP CONSTRAINT clinical_measurements_deleted_by_fkey;
ALTER TABLE gynfem.patients
    DROP CONSTRAINT patients_created_by_fkey,
    DROP CONSTRAINT patients_updated_by_fkey,
    DROP CONSTRAINT patients_deleted_by_fkey;

DROP TABLE gynfem.user_profiles;
DROP FUNCTION gynfem.forbid_created_changes();
