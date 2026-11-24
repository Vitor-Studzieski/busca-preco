import json
import logging
from datetime import datetime, timezone
from uuid import uuid4


class JSONLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage() if record.name.startswith("pricing") else "Evento do servidor",
        }
        for key in ("collection_job", "store", "status", "duration_ms", "request_id"):
            if getattr(record, key, None) is not None:
                payload[key] = getattr(record, key)
        if record.exc_info and record.exc_info[0]:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid4().hex
        response = self.get_response(request)
        response.headers["X-Request-ID"] = request.request_id
        return response
