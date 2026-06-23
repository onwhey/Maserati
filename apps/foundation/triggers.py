"""项目底座模块：定义触发来源语义；不读写数据库，不访问外部服务，不涉及交易执行。"""

from enum import StrEnum


class TriggerSource(StrEnum):
    CELERY_BEAT = "celery_beat"
    CELERY_WORKER = "celery_worker"
    MANAGEMENT_COMMAND = "management_command"
    OPS_CONSOLE = "ops_console"
    MANUAL_REVIEW = "manual_review"
    RUNTIME_GUARD = "runtime_guard"
    SYSTEM = "system"
    TEST = "test"
    DRY_RUN = "dry_run"

