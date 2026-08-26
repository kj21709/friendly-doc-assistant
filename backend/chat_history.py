"""List and clear chat history for a validated user name."""
import os

import boto3
from boto3.dynamodb.conditions import Key

from common import parse_body, require_name, response


history = boto3.resource("dynamodb").Table(os.environ["HISTORY_TABLE"])


def history_items(user_id):
    """Return every turn for a user, including paginated DynamoDB results."""
    items = []
    kwargs = {
        "KeyConditionExpression": Key("userId").eq(user_id),
        "ScanIndexForward": True,
    }
    while True:
        result = history.query(**kwargs)
        items.extend(result.get("Items", []))
        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def handler(event, _context):
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()
        if method == "GET":
            user_id = require_name((event.get("queryStringParameters") or {}).get("userId"))
            items = history_items(user_id)
            fields = ("timestamp", "documentId", "question", "response", "createdAt")
            return response(200, {"history": [{key: item[key] for key in fields if key in item} for item in items]})

        if method == "DELETE":
            user_id = require_name(parse_body(event).get("userId"))
            items = history_items(user_id)
            with history.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={"userId": user_id, "timestamp": item["timestamp"]})
            return response(200, {"cleared": len(items)})

        return response(405, {"message": "Method not allowed."})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
    except Exception as exc:
        print(f"history error: {exc}")
        return response(500, {"message": "Chat history could not be updated right now."})
