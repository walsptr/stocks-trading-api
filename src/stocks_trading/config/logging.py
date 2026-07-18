import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo


class JsonFormatter(logging.Formatter):
    def __init__(self, timezone: ZoneInfo) -> None:
        super().__init__()
        self.timezone = timezone

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(self.timezone).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str, timezone: ZoneInfo | None = None) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(timezone or ZoneInfo("Asia/Jakarta")))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
