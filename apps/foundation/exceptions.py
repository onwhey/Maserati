"""项目底座模块：定义基础异常语义；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations


class ProjectError(Exception):
    reason_code = "project_error"

    def __init__(self, message: str, *, trace_id: str = "") -> None:
        super().__init__(message)
        self.trace_id = trace_id


class ConfigurationError(ProjectError):
    reason_code = "configuration_error"


class PermissionDeniedError(ProjectError):
    reason_code = "permission_denied"


class ParameterError(ProjectError):
    reason_code = "parameter_error"


class DatabaseConnectionError(ProjectError):
    reason_code = "database_connection_error"


class RedisConnectionError(ProjectError):
    reason_code = "redis_connection_error"


class ExternalServiceError(ProjectError):
    reason_code = "external_service_error"


class GatewayError(ProjectError):
    reason_code = "gateway_error"


class SafetyAdmissionError(ProjectError):
    reason_code = "safety_admission_error"


class IdempotencyConflictError(ProjectError):
    reason_code = "idempotency_conflict"


class StateConflictError(ProjectError):
    reason_code = "state_conflict"


class UnknownExternalResultError(ProjectError):
    reason_code = "unknown_external_result"


class NotificationDeliveryError(ProjectError):
    reason_code = "notification_delivery_error"


class UnexpectedSystemError(ProjectError):
    reason_code = "unexpected_system_error"

