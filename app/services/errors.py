"""Errores del dominio. No conocen HTTP: `app/core/errors.py` los traduce al
formato uniforme (`docs/API_SPEC.md` §2.5). Sus mensajes nunca llevan datos."""


class DomainError(Exception):
    code: str = "domain_error"
    message: str = "La operación no se pudo completar."


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass


class Rejected(DomainError):
    """La entrada pasó el esquema, pero una regla externa la rechaza (422)."""


class PatientNotFound(NotFound):
    code = "patient_not_found"
    message = "Paciente no encontrada."


class MeasurementNotFound(NotFound):
    code = "measurement_not_found"
    message = "Medición no encontrada."


class PredictionNotFound(NotFound):
    code = "prediction_not_found"
    message = "Predicción no encontrada."


class PatientAlreadyExists(Conflict):
    code = "patient_already_exists"
    message = "Ya hay una paciente activa con ese documento."


class MeasurementAlreadyCorrected(Conflict):
    code = "measurement_already_corrected"
    message = "Esa medición ya fue corregida."


class UserNotFound(NotFound):
    code = "user_not_found"
    message = "Usuario no encontrado."


class UserAlreadyExists(Conflict):
    code = "user_already_exists"
    message = "Ya existe un usuario con ese correo."


class LastActiveAdmin(Conflict):
    code = "last_active_admin"
    message = "No se puede dejar el sistema sin un administrador activo."


class UserRejected(Rejected):
    code = "user_rejected"
    message = "El servicio de autenticación rechazó los datos del usuario."


class WeakPassword(Rejected):
    code = "weak_password"
    message = "La contraseña no cumple la política del servicio de autenticación."
