-- Reversión de 0009. Se pierden los parámetros guardados y su historial de
-- valores: vuelven a regir los valores por defecto del código. Revertirla en
-- producción es una decisión, no un trámite.

-- Como en la reversión de la 0008: la auditoría es de solo inserción, así que
-- si ya registró cambios de parámetros esas filas no se pueden borrar ni
-- exigirles la restricción anterior. Entonces se restaura `NOT VALID`: rige para
-- toda fila nueva y respeta las existentes. Sin esas filas, el catálogo queda
-- exactamente como antes de la 0009.
ALTER TABLE gynfem.audit_log DROP CONSTRAINT audit_log_entity_type_valid;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM gynfem.audit_log WHERE entity_type = 'system_setting') THEN
        ALTER TABLE gynfem.audit_log ADD CONSTRAINT audit_log_entity_type_valid
            CHECK (entity_type IN ('patient', 'clinical_measurement', 'prediction', 'user')) NOT VALID;
    ELSE
        ALTER TABLE gynfem.audit_log ADD CONSTRAINT audit_log_entity_type_valid
            CHECK (entity_type IN ('patient', 'clinical_measurement', 'prediction', 'user'));
    END IF;
END;
$$;

DROP TABLE gynfem.system_settings;
DROP FUNCTION gynfem.forbid_setting_update();
