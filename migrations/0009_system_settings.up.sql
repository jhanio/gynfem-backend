-- 0009 — Fase 16: parámetros del sistema (HU011) y su entidad de auditoría.
--
-- Los parámetros que el administrador ajusta sin desplegar. Ninguno es clínico:
-- el catálogo de claves, con su tipo, su rango y su valor por defecto, vive en
-- el código; aquí solo el formato de la clave y el tamaño del valor.
--
-- Solo inserción, como la auditoría: cada cambio es una fila nueva con su autor,
-- y el valor vigente de una clave es su última fila. Así la tabla conserva todos
-- los valores anteriores sin llevar valores a `audit_log`, que solo guarda
-- nombres. Sin filas para una clave, rige el valor por defecto del código: la
-- migración no siembra nada. Sin `updated_*` ni `deleted_*`: nada se reescribe
-- ni se da de baja. El id es un entero de identidad: nunca aparece en una URL.

CREATE TABLE gynfem.system_settings (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  uuid NOT NULL
                    CONSTRAINT system_settings_created_by_fkey REFERENCES gynfem.user_profiles (id)
                        ON DELETE RESTRICT ON UPDATE RESTRICT,
    key         text NOT NULL
                    CONSTRAINT system_settings_key_format CHECK (key ~ '^[a-z][a-z0-9_]*$'),
    value       text NOT NULL
                    CONSTRAINT system_settings_value_length CHECK (char_length(value) BETWEEN 1 AND 200)
);
ALTER TABLE gynfem.system_settings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE gynfem.system_settings FROM PUBLIC, anon, authenticated;

-- El valor vigente de una clave: su fila más reciente.
CREATE INDEX system_settings_key_idx ON gynfem.system_settings (key, id DESC);

CREATE FUNCTION gynfem.forbid_setting_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'los parámetros son de solo inserción: un cambio es una fila nueva';
END;
$$;
REVOKE ALL ON FUNCTION gynfem.forbid_setting_update() FROM PUBLIC, anon, authenticated;

CREATE TRIGGER system_settings_forbid_update BEFORE UPDATE ON gynfem.system_settings
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_setting_update();
CREATE TRIGGER system_settings_forbid_delete BEFORE DELETE ON gynfem.system_settings
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_physical_delete();
CREATE TRIGGER system_settings_forbid_truncate BEFORE TRUNCATE ON gynfem.system_settings
    FOR EACH STATEMENT EXECUTE FUNCTION gynfem.forbid_physical_delete();

CREATE POLICY system_settings_deny_data_api ON gynfem.system_settings
    AS RESTRICTIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

COMMENT ON TABLE gynfem.system_settings IS 'Parámetros no clínicos del sistema (HU011). Solo inserción: el vigente es la última fila de cada clave.';

-- El cambio de un parámetro (HU011) también se audita.
ALTER TABLE gynfem.audit_log DROP CONSTRAINT audit_log_entity_type_valid;
ALTER TABLE gynfem.audit_log ADD CONSTRAINT audit_log_entity_type_valid
    CHECK (entity_type IN ('patient', 'clinical_measurement', 'prediction', 'user', 'system_setting'));
