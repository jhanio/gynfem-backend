-- 0007 — Fase 10: identidad mínima de la paciente, correcciones de mediciones
-- y bajas irreversibles.
--
-- 1. Identidad (decisión A de la Fase 10, principio de minimización): tipo y
--    número de documento, nombres y apellidos. Sin fecha de nacimiento: la
--    edad se registra en cada medición, que es la entrada del modelo.
--    `search_key` es la forma normalizada (minúsculas, sin tildes) de nombres
--    y apellidos que usa la búsqueda; la calcula el backend y nunca se expone.
--    Las columnas son NOT NULL sin valor por defecto: la tabla está vacía hasta
--    esta fase. Si tuviera filas, la migración fallaría entera.
-- 2. Corrección de una medición (decisión C): la corrección es una medición
--    nueva que apunta a la que corrige; una medición se corrige una sola vez.
-- 3. Pendientes de docs/ERD.md §4.3 (decisión F): la baja lógica no se deshace
--    ni se reescribe, `created_*` es inmutable, y los valores de una medición
--    también: corregir nunca reescribe lo que se evaluó.

ALTER TABLE gynfem.patients
    ADD COLUMN document_type text NOT NULL
        CONSTRAINT patients_document_type_valid CHECK (document_type IN ('DNI', 'CE', 'PASAPORTE')),
    ADD COLUMN document_number text NOT NULL,
    ADD COLUMN given_names text NOT NULL
        CONSTRAINT patients_given_names_length CHECK (char_length(btrim(given_names)) BETWEEN 1 AND 100),
    ADD COLUMN family_names text NOT NULL
        CONSTRAINT patients_family_names_length CHECK (char_length(btrim(family_names)) BETWEEN 1 AND 100),
    ADD COLUMN search_key text NOT NULL
        CONSTRAINT patients_search_key_not_blank CHECK (btrim(search_key) <> ''),
    -- DNI: 8 dígitos (RENIEC). CE y pasaporte: regla provisional, pendiente de
    -- confirmar con GynFem.
    ADD CONSTRAINT patients_document_number_format CHECK (
        (document_type = 'DNI' AND document_number ~ '^[0-9]{8}$')
        OR (document_type IN ('CE', 'PASAPORTE') AND document_number ~ '^[A-Z0-9]{4,20}$')
    );

-- Un solo registro activo por documento; el de una paciente dada de baja se puede reutilizar.
CREATE UNIQUE INDEX patients_active_document_idx
    ON gynfem.patients (document_type, document_number) WHERE deleted_at IS NULL;

ALTER TABLE gynfem.clinical_measurements
    ADD COLUMN replaces_measurement_id uuid
        CONSTRAINT clinical_measurements_replaces_fkey REFERENCES gynfem.clinical_measurements (id)
            ON DELETE RESTRICT ON UPDATE RESTRICT
        CONSTRAINT clinical_measurements_replaces_once UNIQUE;

-- Baja irreversible y procedencia inmutable. En `clinical_measurements`, además,
-- todo salvo la baja y `updated_*`. `predictions` ya tiene su propio trigger
-- (0004), que solo admite la baja.
CREATE FUNCTION gynfem.forbid_undelete_and_immutable_changes() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE
    mutables text[];
BEGIN
    IF OLD.deleted_at IS NOT NULL
       AND (NEW.deleted_at IS DISTINCT FROM OLD.deleted_at OR NEW.deleted_by IS DISTINCT FROM OLD.deleted_by) THEN
        RAISE EXCEPTION 'una baja lógica no se deshace ni se reescribe';
    END IF;
    IF NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
        RAISE EXCEPTION 'created_at y created_by son inmutables';
    END IF;
    IF TG_TABLE_NAME = 'clinical_measurements' THEN
        mutables := ARRAY['updated_at', 'updated_by', 'deleted_at', 'deleted_by'];
        IF (to_jsonb(NEW) - mutables) IS DISTINCT FROM (to_jsonb(OLD) - mutables) THEN
            RAISE EXCEPTION 'los valores de una medición son inmutables: se corrigen con una medición nueva';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION gynfem.forbid_undelete_and_immutable_changes() FROM PUBLIC, anon, authenticated;

-- Orden alfabético de los BEFORE: `guard` va antes que `set_updated_at`.
CREATE TRIGGER patients_guard BEFORE UPDATE ON gynfem.patients
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_undelete_and_immutable_changes();
CREATE TRIGGER clinical_measurements_guard BEFORE UPDATE ON gynfem.clinical_measurements
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_undelete_and_immutable_changes();

COMMENT ON COLUMN gynfem.patients.search_key IS 'Nombres y apellidos normalizados para la búsqueda. Interno: nunca se expone.';
COMMENT ON COLUMN gynfem.clinical_measurements.replaces_measurement_id IS 'Medición que esta corrige (dada de baja en la misma transacción).';
