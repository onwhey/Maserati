"""项目底座模块：提供日志脱敏过滤器；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

import logging

from .redaction import redact_text


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg))
        if record.args:
            record.args = tuple(redact_text(str(arg)) for arg in record.args)
        return True

