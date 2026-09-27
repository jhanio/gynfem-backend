"""Cliente de la Admin API de Supabase Auth (HU002, decisión aprobada 10).

La clave de servicio solo viaja en las cabeceras de la llamada del backend a
Supabase: nunca en un log, un error ni una respuesta. Supabase se sustituye por
un servidor HTTP en loopback que registra lo que recibe.
"""

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from .auth_claves import CLAVE_SECRETA_FICTICIA

CORREO = "medico.prueba@example.com"
CONTRASENA = "Contrasena-De-Prueba-123"


class SupabaseFalso:
    def __init__(self) -> None:
        self.peticiones: list[dict] = []
        self.respuesta: tuple[int, dict] = (200, {"id": str(uuid.uuid4()), "email": CORREO})
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            def _responder(self):
                largo = int(self.headers.get("Content-Length") or 0)
                cuerpo = self.rfile.read(largo) if largo else b""
                servidor.peticiones.append({
                    "metodo": self.command,
                    "ruta": self.path,
                    "cabeceras": {k.lower(): v for k, v in self.headers.items()},
                    "cuerpo": json.loads(cuerpo) if cuerpo else None,
                })
                estado, datos = servidor.respuesta
                salida = json.dumps(datos).encode()
                self.send_response(estado)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(salida)))
                self.end_headers()
                self.wfile.write(salida)

            do_POST = _responder
            do_DELETE = _responder

            def log_message(self, *args):
                pass

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self._http.server_address[1]}"
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

    def cerrar(self) -> None:
        self._http.shutdown()
        self._http.server_close()


@pytest.fixture
def supabase():
    falso = SupabaseFalso()
    yield falso
    falso.cerrar()


def cliente_admin(url: str):
    from app.auth.supabase_admin import SupabaseAdminClient

    return SupabaseAdminClient(url, CLAVE_SECRETA_FICTICIA, timeout_s=2)


def test_crear_usuario_llama_a_la_admin_api_con_correo_confirmado(supabase):
    esperado = uuid.uuid4()
    supabase.respuesta = (200, {"id": str(esperado), "email": CORREO})

    assert cliente_admin(supabase.url).create_user(CORREO, CONTRASENA) == esperado
    [peticion] = supabase.peticiones
    assert (peticion["metodo"], peticion["ruta"]) == ("POST", "/auth/v1/admin/users")
    assert peticion["cuerpo"] == {"email": CORREO, "password": CONTRASENA, "email_confirm": True}


def test_la_clave_de_servicio_solo_va_en_las_cabeceras(supabase):
    cliente_admin(supabase.url).create_user(CORREO, CONTRASENA)
    [peticion] = supabase.peticiones

    assert peticion["cabeceras"]["apikey"] == CLAVE_SECRETA_FICTICIA
    assert peticion["cabeceras"]["authorization"] == f"Bearer {CLAVE_SECRETA_FICTICIA}"
    assert CLAVE_SECRETA_FICTICIA not in peticion["ruta"]
    assert CLAVE_SECRETA_FICTICIA not in json.dumps(peticion["cuerpo"])


def test_borrar_usuario_llama_a_la_admin_api(supabase):
    usuario = uuid.uuid4()
    supabase.respuesta = (200, {})
    cliente_admin(supabase.url).delete_user(usuario)

    [peticion] = supabase.peticiones
    assert (peticion["metodo"], peticion["ruta"]) == ("DELETE", f"/auth/v1/admin/users/{usuario}")


@pytest.mark.parametrize("cuerpo", [{"error_code": "email_exists", "msg": "x"}, {"code": "email_exists"}])
def test_correo_existente_da_user_already_exists(cuerpo, supabase):
    from app.services.errors import UserAlreadyExists

    supabase.respuesta = (422, cuerpo)
    with pytest.raises(UserAlreadyExists):
        cliente_admin(supabase.url).create_user(CORREO, CONTRASENA)


def test_contrasena_debil_segun_supabase_da_weak_password(supabase):
    from app.services.errors import WeakPassword

    supabase.respuesta = (422, {"error_code": "weak_password"})
    with pytest.raises(WeakPassword):
        cliente_admin(supabase.url).create_user(CORREO, CONTRASENA)


@pytest.mark.parametrize("estado", [400, 401, 403, 500, 503])
def test_otro_error_de_supabase_da_auth_unavailable(estado, supabase):
    from app.auth.errors import AuthUnavailable

    supabase.respuesta = (estado, {"msg": f"fallo con {CLAVE_SECRETA_FICTICIA}"})
    with pytest.raises(AuthUnavailable) as error:
        cliente_admin(supabase.url).create_user(CORREO, CONTRASENA)
    assert CLAVE_SECRETA_FICTICIA not in str(error.value)
    assert CONTRASENA not in str(error.value)


def test_respuesta_sin_id_da_auth_unavailable(supabase):
    from app.auth.errors import AuthUnavailable

    supabase.respuesta = (200, {"email": CORREO})
    with pytest.raises(AuthUnavailable):
        cliente_admin(supabase.url).create_user(CORREO, CONTRASENA)


def test_supabase_inaccesible_da_auth_unavailable():
    from app.auth.errors import AuthUnavailable

    with pytest.raises(AuthUnavailable):
        cliente_admin("http://127.0.0.1:1").create_user(CORREO, CONTRASENA)


def test_el_cliente_no_muestra_la_clave():
    cliente = cliente_admin("http://127.0.0.1:1")

    assert CLAVE_SECRETA_FICTICIA not in repr(cliente)
    assert CLAVE_SECRETA_FICTICIA not in str(vars(cliente))
