import base64
import hashlib
import json
import os
import re
from decimal import Decimal


ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": ALLOWED_ORIGIN,
            "access-control-allow-headers": "content-type",
            "access-control-allow-methods": "GET,POST,DELETE,OPTIONS",
        },
        "body": json.dumps(body, default=_json_default),
    }


def parse_body(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def require_name(value):
    name = " ".join(str(value or "").strip().split())
    if not 2 <= len(name) <= 80:
        raise ValueError("Name must contain 2 to 80 characters.")
    if not re.fullmatch(r"[\w .'-]+", name, flags=re.UNICODE):
        raise ValueError("Name contains unsupported characters.")
    return name


def user_key(name):
    """Stable, path-safe key. DynamoDB still stores the supplied name as userId."""
    return hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:32]


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Cannot serialize {type(value)}")
