-- Reversión de 0001. Sin CASCADE: si queda alguna tabla, falla en vez de borrarla.
DROP FUNCTION gynfem.forbid_physical_delete();
DROP FUNCTION gynfem.set_updated_at();
DROP SCHEMA gynfem;
