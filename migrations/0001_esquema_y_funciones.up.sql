-- 0001 — Esquema propio de GynFem y funciones de trigger comunes.
--
-- Las tablas viven en `gynfem`, no en `public`: Supabase expone `public` por su
-- Data API con la anon key, que es pública (va en el frontend). Un esquema que
-- la Data API no expone es una barrera más, además de RLS y de REVOKE
-- (docs/SECURITY.md). Los roles `anon` y `authenticated` son los de Supabase.

CREATE SCHEMA gynfem;
COMMENT ON SCHEMA gynfem IS 'Datos clínicos de GynFem. Fuera de la Data API; solo el backend accede.';
REVOKE ALL ON SCHEMA gynfem FROM PUBLIC, anon, authenticated;

-- Mantiene `updated_at` en todo UPDATE.
CREATE FUNCTION gynfem.set_updated_at() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- Nada se borra físicamente: el borrado es lógico (`deleted_at`). Se usa en
-- triggers BEFORE DELETE (por fila) y BEFORE TRUNCATE (por sentencia).
CREATE FUNCTION gynfem.forbid_physical_delete() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'borrado físico prohibido en %.%: use el borrado lógico (deleted_at)',
        TG_TABLE_SCHEMA, TG_TABLE_NAME;
END;
$$;

REVOKE ALL ON FUNCTION gynfem.set_updated_at() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION gynfem.forbid_physical_delete() FROM PUBLIC, anon, authenticated;
