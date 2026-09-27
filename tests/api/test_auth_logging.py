"""Logs y errores de la autenticación (decisión aprobada 11).

Se registra el identificador del usuario y el resultado de la autorización,
nunca el token, la contraseña, el correo ni un dato clínico. Los centinelas van
dentro de tokens, cuerpos y cabeceras; si aparecen en la salida, algo filtra.
"""

import json

from .api_constantes import ENTRADA_NORMAL
from .auth_claves import MEDICO_ID, cabecera

CORREO_CENTINELA = "centinela.correo@example.com"
CONTRASENA_CENTINELA = "CentinelaClave-9999-XYZ"
CLAIM_CENTINELA = "centinela-claim-7777"


def lineas_de(texto: str) -> list[dict]:
    return [json.loads(l) for l in texto.splitlines() if l.startswith("{")]


def test_logs_y_errores_sin_token_contrasena_ni_correo(crear_cliente, emisor, capsys):
    valido = emisor.token(MEDICO_ID, email=CORREO_CENTINELA, nota=CLAIM_CENTINELA)
    caducado = emisor.token(MEDICO_ID, exp=1, iat=0, email=CORREO_CENTINELA)
    otro_emisor = emisor.token(MEDICO_ID, iss="https://otro.supabase.co/auth/v1", email=CORREO_CENTINELA)
    basura = f"{CLAIM_CENTINELA}.{CORREO_CENTINELA}.{CONTRASENA_CENTINELA}"
    medico = crear_cliente(rol=None)
    admin = crear_cliente(rol="administrador")

    respuestas = [
        medico.post("/api/v1/predict", json=ENTRADA_NORMAL, headers=cabecera(valido)),
        medico.post("/api/v1/predict", json=ENTRADA_NORMAL, headers=cabecera(caducado)),
        medico.post("/api/v1/predict", json=ENTRADA_NORMAL, headers=cabecera(otro_emisor)),
        medico.post("/api/v1/predict", json=ENTRADA_NORMAL, headers=cabecera(basura)),
        medico.get("/api/v1/users", headers=cabecera(valido)),
        # Un 422 por contraseña corta y un alta que llega al servicio (sin base: falla).
        admin.post("/api/v1/users", json={"email": CORREO_CENTINELA, "password": "corta",
                                          "full_name": "Centinela Prueba", "role": "medico"}),
        admin.post("/api/v1/users", json={"email": CORREO_CENTINELA, "password": CONTRASENA_CENTINELA,
                                          "full_name": "Centinela Prueba", "role": "medico"}),
    ]
    salida = capsys.readouterr()

    for fuga in (valido, caducado, otro_emisor, basura, CORREO_CENTINELA, CONTRASENA_CENTINELA, CLAIM_CENTINELA):
        assert fuga not in salida.out and fuga not in salida.err
        for respuesta in respuestas:
            assert fuga not in respuesta.text
    assert [r.status_code for r in respuestas[:5]] == [200, 401, 401, 401, 403]


def test_log_de_autorizacion_lleva_user_id_y_resultado(crear_cliente, capsys):
    capsys.readouterr()
    crear_cliente(rol="medico").post("/api/v1/predict", json=ENTRADA_NORMAL)
    crear_cliente(rol="medico").get("/api/v1/users")
    crear_cliente(rol=None).get("/api/v1/me")
    lineas = [l for l in lineas_de(capsys.readouterr().out) if l["logger"] == "gynfem.auth"]

    assert [(l.get("user_id"), l["auth_outcome"]) for l in lineas] == [
        (str(MEDICO_ID), "allowed"),
        (str(MEDICO_ID), "forbidden"),
        (None, "not_authenticated"),
    ]
    base = {"timestamp", "level", "logger", "message", "request_id"}
    for linea in lineas:
        assert set(linea) - base <= {"user_id", "auth_outcome"}


def test_las_rutas_publicas_no_registran_autorizacion(crear_cliente, capsys):
    capsys.readouterr()
    crear_cliente(rol=None).get("/api/v1/health")

    assert not [l for l in lineas_de(capsys.readouterr().out) if l["logger"] == "gynfem.auth"]
