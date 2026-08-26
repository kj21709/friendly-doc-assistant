import os

import boto3
from boto3.dynamodb.conditions import Key

from common import require_name, response

table = boto3.resource("dynamodb").Table(os.environ["DOCUMENTS_TABLE"])

def handler(event, _context):
    try:
        user_id = require_name((event.get("queryStringParameters") or {}).get("userId"))
        items = table.query(KeyConditionExpression=Key("userId").eq(user_id)).get("Items", [])
        items.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
        fields = ("documentId", "filename", "status", "createdAt", "chunkCount")
        return response(200, {"documents": [{k: item.get(k) for k in fields} for item in items]})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
    except Exception as exc:
        print(f"list documents error: {exc}")
        return response(500, {"message": "Could not list documents."})
