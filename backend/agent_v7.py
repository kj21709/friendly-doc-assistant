"""HTTP Lambda adaptation of the supplied agent_v7.py."""
import io
import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone

import boto3
import numpy as np
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

from common import parse_body, require_name, response


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("BEDROCK_REGION", "us-east-1"))
history = boto3.resource("dynamodb").Table(os.environ["HISTORY_TABLE"])
documents = boto3.resource("dynamodb").Table(os.environ["DOCUMENTS_TABLE"])
BUCKET = os.environ["DOCUMENT_BUCKET"]
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
INFERENCE_PROFILE_ARN = os.environ.get("BEDROCK_INFERENCE_PROFILE_ARN", "").strip()
LLM_MODEL_ID = os.environ.get(
    "BEDROCK_LLM_MODEL_ID",
    os.environ.get("LLM_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
).strip()
USE_INFERENCE_PROFILE = os.environ.get("BEDROCK_USE_INFERENCE_PROFILE", "true").strip().lower() in {
    "1", "true", "yes", "y",
}
SONNET_FALLBACK_MODEL_ID = os.environ.get(
    "BEDROCK_SONNET_FALLBACK_MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0"
).strip()
NOVA_LITE_FALLBACK_MODEL_ID = os.environ.get(
    "BEDROCK_NOVA_LITE_MODEL_ID", "amazon.nova-lite-v1:0"
).strip()
NOVA_MICRO_FALLBACK_MODEL_ID = os.environ.get(
    "BEDROCK_NOVA_MICRO_MODEL_ID", "amazon.nova-micro-v1:0"
).strip()
MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "500"))
TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.2"))
TOP_P = float(os.environ.get("BEDROCK_TOP_P", "0.9"))
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "512"))
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "6"))

SYSTEM_PROMPT = """You are Dave, a friendly and approachable assistant.
Answer strictly from PROVIDED DOCUMENT EXCERPTS.
If the excerpts do not contain enough information, respond exactly: "I couldn't find that information in the provided document."
Use prior conversation for conversational continuity.
Every factual statement must be supported by an excerpt.
Do not invent page numbers, procedures, names, dates, or missing steps.
Prior conversation may clarify what the user means, but it is not evidence.
Be clear, practical, and concise. Greet the user only when there is no prior conversation."""


def embed(text):
    result = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": EMBEDDING_DIMENSIONS, "normalize": True}),
        contentType="application/json", accept="application/json")
    return json.loads(result["body"].read())["embedding"]


def retrieve(vector_key, chunks_key, question, k=4):
    raw_vectors = s3.get_object(Bucket=BUCKET, Key=vector_key)["Body"].read()
    vectors = np.load(io.BytesIO(raw_vectors), allow_pickle=False)
    chunks = json.loads(s3.get_object(Bucket=BUCKET, Key=chunks_key)["Body"].read())
    query = np.asarray(embed(question), dtype=np.float32)
    scores = vectors @ query
    count = min(k, len(scores))
    top = np.argpartition(scores, -count)[-count:]
    top = top[np.argsort(scores[top])[::-1]]
    return [chunks[int(index)] for index in top]


def previous_turns(user_id, document_id):
    result = history.query(
        KeyConditionExpression=Key("userId").eq(user_id),
        ScanIndexForward=False,
        Limit=MAX_HISTORY * 3,
    )
    items = [x for x in result.get("Items", []) if x.get("documentId") == document_id][:MAX_HISTORY]
    items.reverse()
    return items


def llm_targets():
    """Return configured invocation targets in priority order without duplicates."""
    configured = []
    if USE_INFERENCE_PROFILE and INFERENCE_PROFILE_ARN:
        configured.append(INFERENCE_PROFILE_ARN)
    configured.extend([
        LLM_MODEL_ID,
        SONNET_FALLBACK_MODEL_ID,
        NOVA_LITE_FALLBACK_MODEL_ID,
        NOVA_MICRO_FALLBACK_MODEL_ID,
    ])
    return list(dict.fromkeys(target for target in configured if target))


def inference_config(model_id):
    """Build a Converse configuration supported by the selected model family."""
    config = {"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE}
    if "amazon.nova-" in model_id:
        config["topP"] = TOP_P
    return config


def call_llm(question, chunks, turns):
    excerpts = "\n\n".join(f"<excerpt>{x}</excerpt>" for x in chunks)
    context = "\n".join(f"User: {x['question']}\nAssistant: {x['response']}" for x in turns)
    prompt = f"PRIOR CONVERSATION:\n{context or '(none)'}\n\nPROVIDED DOCUMENT EXCERPTS:\n{excerpts}\n\nQUESTION:\n{question}"
    targets = llm_targets()
    if not targets:
        raise RuntimeError("No Bedrock LLM target is configured.")

    last_error = None
    for position, model_id in enumerate(targets, start=1):
        try:
            logger.info(
                "Invoking Bedrock model",
                extra={
                    "model_id": model_id,
                    "bedrock_region": bedrock.meta.region_name,
                    "fallback_position": position,
                },
            )
            result = bedrock.converse(
                modelId=model_id,
                system=[{"text": SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig=inference_config(model_id),
            )
            return "".join(
                item.get("text", "") for item in result["output"]["message"]["content"]
            ).strip()
        except ClientError as exc:
            last_error = exc
            error = exc.response.get("Error", {})
            logger.warning(
                "Bedrock model invocation failed; trying next configured target",
                extra={
                    "model_id": model_id,
                    "bedrock_region": bedrock.meta.region_name,
                    "error_code": error.get("Code", "Unknown"),
                    "fallback_position": position,
                },
            )

    raise last_error


def handler(event, context):
    try:
        body = parse_body(event)
        user_id = require_name(body.get("userId"))
        document_id = str(body.get("documentId") or "")
        question = " ".join(str(body.get("question") or "").strip().split())
        if not 2 <= len(question) <= 2000:
            return response(400, {"message": "Question must contain 2 to 2,000 characters."})
        document = documents.get_item(Key={"userId": user_id, "documentId": document_id}).get("Item")
        if not document or document.get("status") != "READY":
            return response(409, {"message": "The selected document is not ready."})

        turns = previous_turns(user_id, document_id)
        chunks = retrieve(document["vectorKey"], document["chunksKey"], question)
        answer = call_llm(question, chunks, turns)
        now = datetime.now(timezone.utc).isoformat()
        history.put_item(Item={
            "userId": user_id,
            "timestamp": f"{now}#{uuid.uuid4()}",
            "documentId": document_id,
            "question": question,
            "response": answer,
            "createdAt": now,
        })
        return response(200, {"answer": answer, "documentId": document_id})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
    except Exception:
        request_id = getattr(context, "aws_request_id", "unknown")
        logger.exception(
            "Chat request failed",
            extra={
                "aws_request_id": request_id,
                "model_id": LLM_MODEL_ID,
                "bedrock_region": bedrock.meta.region_name,
            },
        )
        return response(500, {
            "message": "The assistant could not answer right now.",
            "requestId": request_id,
        })
