-- 0005 — Registro de auditoría: quién hizo qué, sobre qué y cuándo.
--
-- Sin valores clínicos por construcción (docs/SECURITY.md): no hay jsonb, ni
-- texto libre, ni columnas de valor anterior o posterior. Cada columna de texto
-- tiene su formato restringido, y `changed_fields` solo admite nombres de
-- campo. La lista concreta de acciones la fija la Fase 10; aquí, su formato.
--
-- Solo inserción: no se actualiza ni se borra, ni siquiera de forma lógica,
-- así que `updated_at` es siempre igual a `created_at` y no hay `deleted_at`.
-- El id es un entero de identidad: nunca aparece en una URL.

CREATE TABLE gynfem.audit_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    actor_user_id   uuid,
    action          text NOT NULL
        CONSTRAINT audit_log_action_format CHECK (action ~ '^[a-z_]+\.[a-z_]+$'),
    entity_type     text NOT NULL
        CONSTRAINT audit_log_entity_type_valid CHECK (entity_type IN ('patient', 'clinical_measurement', 'prediction')),
    entity_id       uuid,
    request_id      text
        CONSTRAINT audit_log_request_id_format CHECK (request_id ~ '^[A-Za-z0-9-]{1,64}$'),
    outcome         text NOT NULL
        CONSTRAINT audit_log_outcome_valid CHECK (outcome IN ('success', 'denied', 'error')),
    changed_fields  text[]
        CONSTRAINT audit_log_changed_fields_are_names CHECK (
            array_position(changed_fields, NULL) IS NULL
            AND array_to_string(changed_fields, ',') ~ '^[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*$'
        )
);
ALTER TABLE gynfem.audit_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE gynfem.audit_log FROM PUBLIC, anon, authenticated;

CREATE INDEX audit_log_entity_idx ON gynfem.audit_log (entity_type, entity_id);
CREATE INDEX audit_log_created_at_idx ON gynfem.audit_log (created_at);

CREATE FUNCTION gynfem.forbid_audit_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'la auditoría es de solo inserción';
END;
$$;
REVOKE ALL ON FUNCTION gynfem.forbid_audit_update() FROM PUBLIC, anon, authenticated;

CREATE TRIGGER audit_log_forbid_update BEFORE UPDATE ON gynfem.audit_log
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_audit_update();
CREATE TRIGGER audit_log_forbid_delete BEFORE DELETE ON gynfem.audit_log
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_physical_delete();
CREATE TRIGGER audit_log_forbid_truncate BEFORE TRUNCATE ON gynfem.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION gynfem.forbid_physical_delete();

COMMENT ON TABLE gynfem.audit_log IS 'Auditoría de solo inserción, sin valores clínicos (SECURITY.md).';
