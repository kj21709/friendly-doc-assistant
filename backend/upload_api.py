import os
import re
import uuid
from datetime import datetime, timezone

import boto3

from common import parse_body, require_name, response, user_key


s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb").Table(os.environ["DOCUMENTS_TABLE"])
BUCKET = os.environ["DOCUMENT_BUCKET"]
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(12 * 1024 * 1024)))


def handler(event, _context):
    try:
        body = parse_body(event)
        user_id = require_name(body.get("userId"))
        filename = str(body.get("filename") or "").strip()
        size = int(body.get("size") or 0)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".txt", ".pdf"}:
            return response(400, {"message": "Only .txt and .pdf files are supported."})
        if size < 1 or size > MAX_BYTES:
            return response(400, {"message": f"File must be between 1 byte and {MAX_BYTES} bytes."})

        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename))[:120]
        document_id = str(uuid.uuid4())
        key = f"documents/{user_key(user_id)}/{document_id}/{safe_name}"
        now = datetime.now(timezone.utc).isoformat()
        ddb.put_item(Item={
            "userId": user_id,
            "documentId": document_id,
            "filename": safe_name,
            "s3Key": key,
            "status": "AWAITING_UPLOAD",
            "createdAt": now,
            "updatedAt": now,
        })
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET, "Key": key, "ContentType": body.get("contentType") or "application/octet-stream"},
            ExpiresIn=900,
        )
        return response(200, {"documentId": document_id, "uploadUrl": url, "s3Key": key})
    except (ValueError, TypeError) as exc:
        return response(400, {"message": str(exc)})
    except Exception as exc:
        print(f"upload-api error: {exc}")
        return response(500, {"message": "Could not create an upload."})
