"""Runner de migraciones: orden, reversión, atomicidad, checksum y salida sin secretos.

Todo corre contra el PostgreSQL embebido de `conftest.py`, nunca contra
Supabase. El catálogo se compara antes y después de cada operación: una
reversión es correcta si deja el catálogo exactamente como estaba.
"""

import os
import re
import shutil
import subprocess
import sys

import psycopg
import pytest

from .conftest import puerto_cerrado

from api.api_constantes import REPO_ROOT

ESQUEMAS_DEL_SISTEMA = ["pg_catalog", "information_schema", "pg_toast"]
ESQUEMA_DE_CONTROL = "gynfem_migrations"

#: Todo objeto creado por el usuario en la base, con su definición.
CONSULTAS_DEL_CATALOGO = {
    "esquemas": """
        SELECT nspname, coalesce(nspacl::text, '') FROM pg_namespace
        WHERE nspname NOT LIKE 'pg\\_%%' AND nspname <> 'information_schema'
    """,
    "relaciones": """
        SELECT n.nspname, c.relname, c.relkind, c.relrowsecurity, coalesce(c.relacl::text, '')
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname <> ALL(%(sistema)s)
    """,
    "columnas": """
        SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
               a.attnotnull, coalesce(pg_get_expr(d.adbin, d.adrelid), '')
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE n.nspname <> ALL(%(sistema)s) AND a.attnum > 0 AND NOT a.attisdropped
    """,
    "restricciones": """
        SELECT n.nspname, conname, pg_get_constraintdef(co.oid)
        FROM pg_constraint co JOIN pg_namespace n ON n.oid = co.connamespace
        WHERE n.nspname <> ALL(%(sistema)s)
    """,
    "indices": """
        SELECT schemaname, indexname, indexdef FROM pg_indexes
        WHERE schemaname <> ALL(%(sistema)s)
    """,
    "triggers": """
        SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid)
        FROM pg_trigger WHERE NOT tgisinternal
    """,
    "funciones": """
        SELECT n.nspname, p.proname, pg_get_functiondef(p.oid), coalesce(p.proacl::text, '')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname <> ALL(%(sistema)s)
    """,
    "privilegios_por_defecto": "SELECT defaclrole::regrole::text, defaclnamespace::regnamespace::text, defaclacl::text FROM pg_default_acl",
}


def catalogo(url: str, excluir_control: bool = False) -> dict[str, list[tuple]]:
    with psycopg.connect(url) as conexion:
        foto = {
            nombre: sorted(
                conexion.execute(consulta, {"sistema": ESQUEMAS_DEL_SISTEMA}).fetchall(),
                key=repr,
            )
            for nombre, consulta in CONSULTAS_DEL_CATALOGO.items()
        }
    if excluir_control:
        foto = {
            nombre: [fila for fila in filas if ESQUEMA_DE_CONTROL not in repr(fila)]
            for nombre, filas in foto.items()
        }
    return foto


def versiones_aplicadas(url: str) -> list[int]:
    with psycopg.connect(url) as conexion:
        filas = conexion.execute(
            f"SELECT version FROM {ESQUEMA_DE_CONTROL}.schema_migrations ORDER BY version"
        ).fetchall()
    return [v for (v,) in filas]


def _ejecutar_cli(args: list[str], env_extra: dict[str, str], cwd) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GYNFEM_")}
    env.update(env_extra)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "app.db.migrate", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# --- Archivos -------------------------------------------------------------------


def test_migraciones_numeradas_sin_huecos_y_con_reversion():
    from app.db.migrate import MIGRATIONS_DIR, discover

    archivos = sorted(p.name for p in MIGRATIONS_DIR.iterdir() if p.suffix == ".sql")
    migraciones = discover(MIGRATIONS_DIR)

    assert [m.version for m in migraciones] == list(range(1, len(migraciones) + 1))
    assert len(migraciones) >= 1
    for m in migraciones:
        prefijo = f"{m.version:04d}_{m.name}"
        assert f"{prefijo}.up.sql" in archivos
        assert f"{prefijo}.down.sql" in archivos
        assert m.down_sql.strip(), f"la reversión de {prefijo} está vacía"
    assert len(archivos) == 2 * len(migraciones), "hay archivos .sql sin pareja o fuera de la serie"


def _copiar_migraciones(tmp_path):
    from app.db.migrate import MIGRATIONS_DIR

    destino = tmp_path / "migraciones"
    shutil.copytree(MIGRATIONS_DIR, destino)
    return destino


@pytest.mark.parametrize(
    "alterar, fragmento",
    [
        (lambda d: next(d.glob("0002_*.down.sql")).unlink(), "0002"),
        (lambda d: next(d.glob("0002_*.up.sql")).rename(d / "0009_salto.up.sql"), "0002"),
        (
            lambda d: next(d.glob("0001_*.up.sql")).write_text(
                "CREATE INDEX CONCURRENTLY i ON t (c);", encoding="utf-8"
            ),
            "CONCURRENTLY",
        ),
    ],
    ids=["sin reversión", "hueco en la numeración", "sentencia no transaccional"],
)
def test_serie_de_migraciones_invalida_se_rechaza(alterar, fragmento, tmp_path):
    from app.db.migrate import MigrationError, discover

    directorio = _copiar_migraciones(tmp_path)
    alterar(directorio)

    with pytest.raises(MigrationError) as error:
        discover(directorio)
    assert fragmento in str(error.value)


def test_checksum_no_depende_del_fin_de_linea(tmp_path):
    """Git en Windows puede convertir LF en CRLF: una migración aplicada desde
    Windows no debe parecer modificada al consultarla desde Linux (Render)."""
    from app.db.migrate import MIGRATIONS_DIR, discover

    directorio = _copiar_migraciones(tmp_path)
    for archivo in directorio.glob("*.sql"):
        texto = archivo.read_bytes().replace(b"\r\n", b"\n")
        archivo.write_bytes(texto.replace(b"\n", b"\r\n"))

    originales = [m.checksum for m in discover(MIGRATIONS_DIR)]
    assert [m.checksum for m in discover(directorio)] == originales


# --- Aplicar y revertir -----------------------------------------------------------


def test_up_aplica_todas_y_registra_su_checksum(base_vacia):
    from app.db.migrate import MIGRATIONS_DIR, discover, upgrade

    migraciones = discover(MIGRATIONS_DIR)
    aplicadas = upgrade(base_vacia)

    assert aplicadas == [m.version for m in migraciones]
    with psycopg.connect(base_vacia) as conexion:
        registradas = dict(
            conexion.execute(
                f"SELECT version, checksum FROM {ESQUEMA_DE_CONTROL}.schema_migrations"
            ).fetchall()
        )
    assert registradas == {m.version: m.checksum for m in migraciones}


def test_up_es_idempotente(base_migrada):
    from app.db.migrate import upgrade

    antes = catalogo(base_migrada)
    assert upgrade(base_migrada) == []
    assert catalogo(base_migrada) == antes


def _numero_de_migraciones() -> int:
    """Se cuenta desde los archivos, sin importar el runner: sirve al parametrizar."""
    return len(list((REPO_ROOT / "migrations").glob("*.up.sql")))


@pytest.mark.parametrize("version", range(1, _numero_de_migraciones() + 1))
def test_cada_migracion_revierte_y_reaplica(version, base_vacia):
    from app.db.migrate import downgrade, upgrade

    upgrade(base_vacia, target=version - 1)
    antes = catalogo(base_vacia)
    upgrade(base_vacia, target=version)
    despues_de_aplicar = catalogo(base_vacia)

    assert downgrade(base_vacia, steps=1) == [version]
    assert catalogo(base_vacia) == antes, f"la reversión de {version:04d} no deja el catálogo como estaba"
    assert upgrade(base_vacia, target=version) == [version]
    assert catalogo(base_vacia) == despues_de_aplicar


def test_down_total_deja_la_base_como_estaba(base_vacia):
    from app.db.migrate import downgrade, upgrade

    inicial = catalogo(base_vacia)
    total = len(upgrade(base_vacia))
    assert downgrade(base_vacia, steps=total) == list(range(total, 0, -1))

    assert catalogo(base_vacia, excluir_control=True) == inicial
    assert versiones_aplicadas(base_vacia) == []


def test_migracion_fallida_a_medias_no_deja_rastro(base_vacia, tmp_path):
    from app.db.migrate import MigrationError, upgrade

    directorio = tmp_path / "serie"
    directorio.mkdir()
    (directorio / "0001_buena.up.sql").write_text("CREATE TABLE buena (id int);", encoding="utf-8")
    (directorio / "0001_buena.down.sql").write_text("DROP TABLE buena;", encoding="utf-8")
    (directorio / "0002_rota.up.sql").write_text(
        "CREATE TABLE parcial (id int);\nSELECT 1 / 0;", encoding="utf-8"
    )
    (directorio / "0002_rota.down.sql").write_text("DROP TABLE parcial;", encoding="utf-8")

    with pytest.raises(MigrationError) as error:
        upgrade(base_vacia, directory=directorio)
    assert "0002" in str(error.value)

    with psycopg.connect(base_vacia) as conexion:
        assert conexion.execute("SELECT to_regclass('public.parcial')").fetchone() == (None,)
        assert conexion.execute("SELECT to_regclass('public.buena')").fetchone() != (None,)
    assert versiones_aplicadas(base_vacia) == [1]


def test_migracion_y_su_registro_son_atomicos(base_vacia, tmp_path):
    """Si el registro en la tabla de control falla, la migración tampoco queda.

    Un mensaje de varias sentencias ya corre en una transacción implícita de
    PostgreSQL; lo que exige la transacción explícita del runner es que el SQL
    de la migración y su registro sean una sola unidad.
    """
    from app.db.migrate import MigrationError, upgrade

    directorio = tmp_path / "serie"
    directorio.mkdir()
    (directorio / "0001_rechaza_registro.up.sql").write_text(
        f"""
        CREATE FUNCTION public.rechazar_v2() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.version = 2 THEN RAISE EXCEPTION 'registro rechazado'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER rechazar_v2 BEFORE INSERT ON {ESQUEMA_DE_CONTROL}.schema_migrations
            FOR EACH ROW EXECUTE FUNCTION public.rechazar_v2();
        """,
        encoding="utf-8",
    )
    (directorio / "0001_rechaza_registro.down.sql").write_text(
        f"DROP TRIGGER rechazar_v2 ON {ESQUEMA_DE_CONTROL}.schema_migrations;\n"
        "DROP FUNCTION public.rechazar_v2();",
        encoding="utf-8",
    )
    (directorio / "0002_tabla.up.sql").write_text("CREATE TABLE sin_registro (id int);", encoding="utf-8")
    (directorio / "0002_tabla.down.sql").write_text("DROP TABLE sin_registro;", encoding="utf-8")

    with pytest.raises(MigrationError) as error:
        upgrade(base_vacia, directory=directorio)
    assert "0002" in str(error.value)

    with psycopg.connect(base_vacia) as conexion:
        assert conexion.execute("SELECT to_regclass('public.sin_registro')").fetchone() == (None,)
    assert versiones_aplicadas(base_vacia) == [1]


def test_migracion_aplicada_modificada_aborta_sin_aplicar_nada(base_vacia, tmp_path):
    from app.db.migrate import MigrationError, upgrade

    directorio = _copiar_migraciones(tmp_path)
    total = len(upgrade(base_vacia, directory=directorio))
    primera = next(directorio.glob("0001_*.up.sql"))
    primera.write_text(primera.read_text(encoding="utf-8") + "\n-- editada\n", encoding="utf-8")
    siguiente = total + 1
    (directorio / f"{siguiente:04d}_nueva.up.sql").write_text("CREATE TABLE nueva (id int);", encoding="utf-8")
    (directorio / f"{siguiente:04d}_nueva.down.sql").write_text("DROP TABLE nueva;", encoding="utf-8")

    with pytest.raises(MigrationError) as error:
        upgrade(base_vacia, directory=directorio)
    assert "0001" in str(error.value)
    assert versiones_aplicadas(base_vacia) == list(range(1, total + 1))


# --- Línea de comandos ----------------------------------------------------------


def test_runner_exige_su_variable(tmp_path):
    resultado = _ejecutar_cli(["status"], {}, tmp_path)

    assert resultado.returncode == 1
    assert "GYNFEM_MIGRATIONS_DATABASE_URL" in resultado.stderr
    assert "Traceback" not in resultado.stderr


def test_runner_lee_el_env_file_y_informa_el_estado(base_migrada, tmp_path):
    env_file = tmp_path / "local.env"
    env_file.write_text(f"GYNFEM_MIGRATIONS_DATABASE_URL={base_migrada}\n", encoding="utf-8")
    total = _numero_de_migraciones()

    resultado = _ejecutar_cli(["--env-file", str(env_file), "status"], {}, tmp_path)

    assert resultado.returncode == 0, resultado.stderr
    assert f"{total} de {total}" in resultado.stdout


CENTINELAS = ("usuario-centinela", "clave-centinela", "base-centinela")


def test_runner_no_imprime_la_cadena_de_conexion_al_fallar(tmp_path):
    url = f"postgresql://{CENTINELAS[0]}:{CENTINELAS[1]}@127.0.0.1:{puerto_cerrado()}/{CENTINELAS[2]}"

    resultado = _ejecutar_cli(["up"], {"GYNFEM_MIGRATIONS_DATABASE_URL": url}, tmp_path)

    assert resultado.returncode == 1
    assert "no se pudo conectar" in resultado.stderr
    tipo = re.search(r"\((\w+)\)", resultado.stderr)
    assert tipo and issubclass(getattr(psycopg, tipo[1], None) or getattr(psycopg.errors, tipo[1]), psycopg.OperationalError), (
        "el tipo de la excepción sí se informa"
    )
    salida = resultado.stdout + resultado.stderr
    assert "Traceback" not in salida
    for centinela in (*CENTINELAS, url):
        assert centinela not in salida


def test_runner_no_imprime_la_cadena_de_conexion_al_funcionar(base_vacia, tmp_path):
    # El servidor embebido no pide contraseña: la del centinela se ignora al conectar.
    url = base_vacia.replace("postgresql://postgres@", f"postgresql://postgres:{CENTINELAS[1]}@")

    for comando in (["up"], ["status"], ["down"]):
        resultado = _ejecutar_cli(comando, {"GYNFEM_MIGRATIONS_DATABASE_URL": url}, tmp_path)
        assert resultado.returncode == 0, resultado.stderr
        salida = resultado.stdout + resultado.stderr
        assert CENTINELAS[1] not in salida
        assert url not in salida
