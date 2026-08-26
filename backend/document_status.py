import os

import boto3
from boto3.dynamodb.conditions import Key

from common import require_name, response


table = boto3.resource("dynamodb").Table(os.environ["DOCUMENTS_TABLE"])


def handler(event, _context):
    try:
        params = event.get("queryStringParameters") or {}
        user_id = require_name(params.get("userId"))
        document_id = str(params.get("documentId") or "")
        item = table.get_item(Key={"userId": user_id, "documentId": document_id}).get("Item")
        if not item:
            return response(404, {"message": "Document not found."})
        return response(200, {"document": item})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
    except Exception as exc:
        print(f"status error: {exc}")
        return response(500, {"message": "Could not retrieve document status."})
