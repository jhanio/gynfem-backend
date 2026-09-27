-- 0008 — Fase 11: perfiles de usuario (rol y estado), el actor de cada registro
-- con clave foránea, y las políticas RLS definitivas.
--
-- 1. Perfil (HU001, HU002). Supabase Auth guarda la cuenta y la contraseña en
--    `auth.users`; aquí solo el rol, el estado y el nombre. El rol vive **solo**
--    aquí (decisión B): el backend lo lee en cada petición y nunca confía en el
--    que declare el token. El correo tampoco se copia: su única fuente es
--    `auth.users`. Un usuario con perfil no se puede borrar de Auth (RESTRICT);
--    se desactiva.
-- 2. Actor. `created_by`, `updated_by`, `deleted_by` y `audit_log.actor_user_id`
--    apuntan al perfil (docs/ERD.md §4.4). Hasta esta fase eran NULL, así que
--    añadir las claves no exige migrar datos.
-- 3. RLS definitivo (decisión C). El backend se conecta como dueño de las tablas
--    y RLS no le aplica: su autoridad es el RBAC de la aplicación. RLS protege el
--    camino de la Data API de Supabase: una política RESTRICTIVE que niega todo a
--    `anon` y `authenticated` en cada tabla. Ninguna política permisiva: es la
--    única forma de que RLS y el RBAC se contradigan.

CREATE TABLE gynfem.user_profiles (
    id          uuid PRIMARY KEY
                    CONSTRAINT user_profiles_auth_user_fkey REFERENCES auth.users (id)
                        ON DELETE RESTRICT ON UPDATE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    created_by  uuid CONSTRAINT user_profiles_created_by_fkey REFERENCES gynfem.user_profiles (id)
                    ON DELETE RESTRICT ON UPDATE RESTRICT,
    updated_by  uuid CONSTRAINT user_profiles_updated_by_fkey REFERENCES gynfem.user_profiles (id)
                    ON DELETE RESTRICT ON UPDATE RESTRICT,
    role        text NOT NULL
                    CONSTRAINT user_profiles_role_valid CHECK (role IN ('medico', 'administrador')),
    is_active   boolean NOT NULL DEFAULT true,
    full_name   text NOT NULL
                    CONSTRAINT user_profiles_full_name_length CHECK (char_length(btrim(full_name)) BETWEEN 1 AND 100)
);
ALTER TABLE gynfem.user_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE gynfem.user_profiles FROM PUBLIC, anon, authenticated;

-- `created_*` es la procedencia del perfil: no se reescribe.
CREATE FUNCTION gynfem.forbid_created_changes() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
        RAISE EXCEPTION 'created_at y created_by son inmutables';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION gynfem.forbid_created_changes() FROM PUBLIC, anon, authenticated;

-- Orden alfabético de los BEFORE: `guard` va antes que `set_updated_at`.
CREATE TRIGGER user_profiles_guard BEFORE UPDATE ON gynfem.user_profiles
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_created_changes();
CREATE TRIGGER user_profiles_set_updated_at BEFORE UPDATE ON gynfem.user_profiles
    FOR EACH ROW EXECUTE FUNCTION gynfem.set_updated_at();
CREATE TRIGGER user_profiles_forbid_delete BEFORE DELETE ON gynfem.user_profiles
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_physical_delete();
CREATE TRIGGER user_profiles_forbid_truncate BEFORE TRUNCATE ON gynfem.user_profiles
    FOR EACH STATEMENT EXECUTE FUNCTION gynfem.forbid_physical_delete();

COMMENT ON TABLE gynfem.user_profiles IS 'Rol y estado de cada usuario de Supabase Auth. Sin correo ni contraseña.';

-- 2. El actor de cada registro es un usuario con perfil.
ALTER TABLE gynfem.patients
    ADD CONSTRAINT patients_created_by_fkey FOREIGN KEY (created_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    ADD CONSTRAINT patients_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    ADD CONSTRAINT patients_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT;
ALTER TABLE gynfem.clinical_measurements
    ADD CONSTRAINT clinical_measurements_created_by_fkey FOREIGN KEY (created_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    ADD CONSTRAINT clinical_measurements_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    ADD CONSTRAINT clinical_measurements_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT;
ALTER TABLE gynfem.predictions
    ADD CONSTRAINT predictions_created_by_fkey FOREIGN KEY (created_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    ADD CONSTRAINT predictions_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    ADD CONSTRAINT predictions_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT;
ALTER TABLE gynfem.audit_log
    ADD CONSTRAINT audit_log_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES gynfem.user_profiles (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT;

-- La gestión de usuarios (HU002) también se audita.
ALTER TABLE gynfem.audit_log DROP CONSTRAINT audit_log_entity_type_valid;
ALTER TABLE gynfem.audit_log ADD CONSTRAINT audit_log_entity_type_valid
    CHECK (entity_type IN ('patient', 'clinical_measurement', 'prediction', 'user'));

-- 3. Políticas RLS definitivas: denegación total a la Data API, tabla por tabla.
CREATE POLICY patients_deny_data_api ON gynfem.patients
    AS RESTRICTIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY clinical_measurements_deny_data_api ON gynfem.clinical_measurements
    AS RESTRICTIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY predictions_deny_data_api ON gynfem.predictions
    AS RESTRICTIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY audit_log_deny_data_api ON gynfem.audit_log
    AS RESTRICTIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY user_profiles_deny_data_api ON gynfem.user_profiles
    AS RESTRICTIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY schema_migrations_deny_data_api ON gynfem_migrations.schema_migrations
    AS RESTRICTIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
