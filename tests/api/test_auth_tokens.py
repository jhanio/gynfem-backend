"""Verificación del JWT de Supabase Auth (HU001, decisiones aprobadas 1–3).

El backend no emite tokens: solo los verifica. Firma ES256 contra el JWKS de
Supabase, expiración, emisor, audiencia y `sub`. Cada token de este archivo se
firma en el propio test (`auth_claves.py`); el JWKS «remoto» es un servidor
HTTP en loopback.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from .auth_claves import (
    ADMIN_ID,
    AUSENTE,
    EMISOR_FICTICIO,
    KID,
    MEDICO_ID,
    Emisor,
    FuenteDeClavesEnMemoria,
    token_sin_firma_valida,
)

RUTA_JWKS = "/auth/v1/.well-known/jwks.json"


def verificador_con(*emisores):
    from app.auth.tokens import TokenVerifier

    return TokenVerifier(FuenteDeClavesEnMemoria(*emisores), EMISOR_FICTICIO)


def rechaza(verificador, token: str, excepcion_nombre: str = "InvalidToken") -> None:
    from app.auth import errors

    with pytest.raises(getattr(errors, excepcion_nombre)):
        verificador.verify(token)


def test_token_valido_devuelve_el_sub(emisor):
    assert verificador_con(emisor).verify(emisor.token(MEDICO_ID)) == MEDICO_ID


def test_firma_de_otra_clave_se_rechaza(emisor):
    """Mismo `kid`, otra clave privada: quien no tiene la clave de Supabase no firma."""
    impostor = Emisor(kid=KID)
    rechaza(verificador_con(emisor), impostor.token(MEDICO_ID))


def test_payload_alterado_se_rechaza(emisor):
    cabecera, _, firma = emisor.token(MEDICO_ID).split(".")
    otra_carga = emisor.token(ADMIN_ID).split(".")[1]
    rechaza(verificador_con(emisor), f"{cabecera}.{otra_carga}.{firma}")


def test_token_caducado_se_rechaza(emisor):
    ahora = int(time.time())
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, iat=ahora - 3720, exp=ahora - 120), "TokenExpired")


def test_iat_en_el_futuro_se_rechaza(emisor):
    ahora = int(time.time())
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, iat=ahora + 3600, exp=ahora + 7200))


def test_otro_emisor_se_rechaza(emisor):
    """Un token de otro proyecto de Supabase, aunque la firma fuera válida."""
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, iss="https://otro-proyecto.supabase.co/auth/v1"))


@pytest.mark.parametrize("audiencia", ["anon", "service_role", "otra-aplicacion"])
def test_otra_audiencia_se_rechaza(audiencia, emisor):
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, aud=audiencia))


def test_hs256_firmado_con_la_clave_publica_se_rechaza(emisor):
    """Confusión de algoritmo: la clave pública es pública; con HS256 cualquiera firmaría."""
    token = token_sin_firma_valida(
        {"alg": "HS256", "typ": "JWT", "kid": KID}, emisor.claims(MEDICO_ID), secreto=emisor.pem_publico()
    )
    rechaza(verificador_con(emisor), token)


def test_alg_none_se_rechaza(emisor):
    token = token_sin_firma_valida({"alg": "none", "typ": "JWT", "kid": KID}, emisor.claims(MEDICO_ID))
    rechaza(verificador_con(emisor), token)


@pytest.mark.parametrize("claim", ["exp", "iat", "sub", "iss", "aud"])
def test_claim_obligatorio_ausente_se_rechaza(claim, emisor):
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, **{claim: AUSENTE}))


@pytest.mark.parametrize("sub", ["no-es-un-uuid", "", "12345"])
def test_sub_que_no_es_uuid_se_rechaza(sub, emisor):
    rechaza(verificador_con(emisor), emisor.token(sub))


def test_kid_desconocido_se_rechaza(emisor):
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, kid="kid-que-no-existe"))


def test_token_sin_kid_se_rechaza(emisor):
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, kid=None))


def test_usuario_anonimo_de_supabase_se_rechaza(emisor):
    rechaza(verificador_con(emisor), emisor.token(MEDICO_ID, is_anonymous=True))


@pytest.mark.parametrize("basura", ["", "no-es-un-jwt", "a.b.c", "a.b", "..."])
def test_texto_que_no_es_un_jwt_se_rechaza(basura, emisor):
    rechaza(verificador_con(emisor), basura)


# --- JWKS remoto (servidor en loopback) ----------------------------------------------


class ServidorJwks:
    """Sirve un JWKS mutable en `127.0.0.1` y registra cada ruta pedida.

    `cuerpo_crudo` sustituye la respuesta (una página de mantenimiento, un JSON sin claves).
    """

    def __init__(self) -> None:
        self.claves: list[dict] = []
        self.rutas: list[str] = []
        self.cuerpo_crudo: bytes | None = None
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                servidor.rutas.append(self.path)
                cuerpo = servidor.cuerpo_crudo or json.dumps({"keys": servidor.claves}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *args):
                pass

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self._http.server_address[1]}"
        self._hilo = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._hilo.start()

    def cerrar(self) -> None:
        self._http.shutdown()
        self._http.server_close()


@pytest.fixture
def servidor_jwks():
    servidor = ServidorJwks()
    yield servidor
    servidor.cerrar()


def verificador_remoto(url_supabase: str):
    from app.auth.tokens import JwksKeySource, TokenVerifier

    return TokenVerifier(JwksKeySource(url_supabase, timeout_s=2), EMISOR_FICTICIO)


def test_jwks_se_descarga_de_la_ruta_de_supabase_y_se_cachea(servidor_jwks, emisor):
    servidor_jwks.claves = [emisor.jwk()]
    verificador = verificador_remoto(servidor_jwks.url)

    assert verificador.verify(emisor.token(MEDICO_ID)) == MEDICO_ID
    assert verificador.verify(emisor.token(ADMIN_ID)) == ADMIN_ID
    assert servidor_jwks.rutas == [RUTA_JWKS]


def test_rotacion_de_clave_recarga_el_jwks(servidor_jwks, emisor):
    servidor_jwks.claves = [emisor.jwk()]
    verificador = verificador_remoto(servidor_jwks.url)
    assert verificador.verify(emisor.token(MEDICO_ID)) == MEDICO_ID

    nueva = Emisor(kid="clave-rotada")
    servidor_jwks.claves = [emisor.jwk(), nueva.jwk()]

    assert verificador.verify(nueva.token(MEDICO_ID)) == MEDICO_ID
    assert servidor_jwks.rutas == [RUTA_JWKS, RUTA_JWKS]


def test_kids_inventados_no_recargan_el_jwks_en_cada_peticion(servidor_jwks, emisor):
    """Un atacante no puede convertir cada petición en una descarga del JWKS."""
    servidor_jwks.claves = [emisor.jwk()]
    verificador = verificador_remoto(servidor_jwks.url)
    for i in range(5):
        rechaza(verificador, emisor.token(MEDICO_ID, kid=f"inventado-{i}"))

    assert len(servidor_jwks.rutas) <= 2


def test_jwks_inaccesible_da_auth_unavailable(emisor):
    from app.auth.errors import AuthUnavailable

    with pytest.raises(AuthUnavailable):
        verificador_remoto("http://127.0.0.1:1").verify(emisor.token(MEDICO_ID))


def test_las_urls_salen_de_la_url_del_proyecto(configurar):
    from app.core.config import load_settings

    configurar(environment="development", cors_origins="http://localhost:5173",
               supabase_url="https://abcdefghij.supabase.co")
    settings = load_settings()

    assert settings.jwt_issuer == "https://abcdefghij.supabase.co/auth/v1"
    assert settings.jwks_url == f"https://abcdefghij.supabase.co{RUTA_JWKS}"


@pytest.mark.parametrize(
    "cuerpo", [b"<html>mantenimiento</html>", b'{"keys": []}', b'{"keys": [{"kty": "desconocido"}]}', b"[]"]
)
def test_jwks_que_no_es_un_jwks_valido_da_auth_unavailable(cuerpo, servidor_jwks, emisor):
    """Una respuesta 200 que no es un JWKS utilizable es una dependencia caída (503), no un 500."""
    from app.auth.errors import AuthUnavailable

    servidor_jwks.cuerpo_crudo = cuerpo
    with pytest.raises(AuthUnavailable):
        verificador_remoto(servidor_jwks.url).verify(emisor.token(MEDICO_ID))
