"""Reglas de negocio de pacientes (HU003, HU004) y de su baja lógica.

Cada operación es **una** transacción: la escritura y su registro de auditoría
se confirman juntos o no se confirma ninguno. No conoce HTTP.
"""

import unicodedata
from typing import Any
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.db.pool import database_transaction
from app.repositories import audit as audit_repo
from app.repositories import patients as patients_repo
from app.services.actor import Actor
from app.services.errors import PatientAlreadyExists, PatientNotFound

#: Dígitos del documento que la búsqueda deja ver.
DIGITOS_VISIBLES = 3


def normalizar_para_busqueda(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios simples: «Pérez  García» → «perez garcia»."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_marcas = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return " ".join(sin_marcas.casefold().split())


def clave_de_busqueda(given_names: str, family_names: str) -> str:
    """Con espacios en los extremos: la búsqueda es por prefijo de cualquier palabra."""
    return f" {normalizar_para_busqueda(given_names)} {normalizar_para_busqueda(family_names)} "


def enmascarar(numero: str) -> str:
    return "*" * max(len(numero) - DIGITOS_VISIBLES, 0) + numero[-DIGITOS_VISIBLES:]


def resumen(fila: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": fila["id"],
        "document_type": fila["document_type"],
        "document_number_masked": enmascarar(fila["document_number"]),
        "given_names": fila["given_names"],
        "family_names": fila["family_names"],
    }


class PatientService:
    def __init__(self, pool: ConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    def create(self, datos: dict[str, str], actor: Actor, request_id: str | None) -> dict[str, Any]:
        try:
            with database_transaction(self._pool, self._settings) as conexion:
                paciente = patients_repo.insert_patient(
                    conexion, datos, clave_de_busqueda(datos["given_names"], datos["family_names"]), actor.user_id
                )
                audit_repo.insert_audit(
                    conexion, action="patient.create", entity_type="patient", entity_id=paciente["id"],
                    actor_user_id=actor.user_id, request_id=request_id,
                )
        except psycopg.errors.UniqueViolation:
            raise PatientAlreadyExists() from None
        return paciente

    def get(self, patient_id: UUID) -> dict[str, Any]:
        with database_transaction(self._pool, self._settings) as conexion:
            paciente = patients_repo.get_active(conexion, patient_id)
        if paciente is None:
            raise PatientNotFound()
        return paciente

    def search_by_document(self, document_type: str, document_number: str, limit: int, offset: int) -> tuple[list, bool]:
        with database_transaction(self._pool, self._settings) as conexion:
            filas = patients_repo.find_by_document(conexion, document_type, document_number, limit + 1, offset)
        return [resumen(f) for f in filas[:limit]], len(filas) > limit

    def search_by_name(self, nombre: str, limit: int, offset: int) -> tuple[list, bool]:
        with database_transaction(self._pool, self._settings) as conexion:
            filas = patients_repo.find_by_name_prefix(conexion, normalizar_para_busqueda(nombre), limit + 1, offset)
        return [resumen(f) for f in filas[:limit]], len(filas) > limit

    def update(self, patient_id: UUID, cambios: dict[str, str], actor: Actor, request_id: str | None) -> dict[str, Any]:
        try:
            with database_transaction(self._pool, self._settings) as conexion:
                actual = patients_repo.get_active(conexion, patient_id, for_update=True)
                if actual is None:
                    raise PatientNotFound()
                nombres = {**actual, **cambios}
                paciente = patients_repo.update_patient(
                    conexion, patient_id, cambios,
                    clave_de_busqueda(nombres["given_names"], nombres["family_names"]), actor.user_id,
                )
                audit_repo.insert_audit(
                    conexion, action="patient.update", entity_type="patient", entity_id=patient_id,
                    actor_user_id=actor.user_id, request_id=request_id,
                    # Solo los nombres de los campos, nunca sus valores.
                    changed_fields=sorted(cambios),
                )
        except psycopg.errors.UniqueViolation:
            raise PatientAlreadyExists() from None
        return paciente

    def deactivate(self, patient_id: UUID, actor: Actor, request_id: str | None) -> None:
        with database_transaction(self._pool, self._settings) as conexion:
            if not patients_repo.deactivate_patient(conexion, patient_id, actor.user_id):
                raise PatientNotFound()
            audit_repo.insert_audit(
                conexion, action="patient.deactivate", entity_type="patient", entity_id=patient_id,
                actor_user_id=actor.user_id, request_id=request_id,
            )
