"""S3-triggered adaptation of the supplied embed_documents_v5_s3.py."""
import io
import json
import os
import re
from datetime import datetime, timezone

import boto3
import numpy as np
from pypdf import PdfReader


s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("BEDROCK_REGION", "us-east-1"))
documents = boto3.resource("dynamodb").Table(os.environ["DOCUMENTS_TABLE"])
BUCKET = os.environ["DOCUMENT_BUCKET"]
MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "150"))
MAX_CHUNKS = int(os.environ.get("MAX_CHUNKS", "2000"))
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "512"))


def extract_text(raw, key):
    if key.lower().endswith(".txt"):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252", errors="replace")
    reader = PdfReader(io.BytesIO(raw))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def split_text(text):
    text = re.sub(r"\r\n?", "\n", text).strip()
    chunks, start = [], 0
    while start < len(text) and len(chunks) < MAX_CHUNKS:
        hard_end = min(start + CHUNK_SIZE, len(text))
        end = hard_end
        if hard_end < len(text):
            break_at = max(text.rfind("\n", start + CHUNK_SIZE // 2, hard_end), text.rfind(" ", start + CHUNK_SIZE // 2, hard_end))
            if break_at > start:
                end = break_at
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def embedding(text):
    result = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": EMBEDDING_DIMENSIONS, "normalize": True}),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(result["body"].read())["embedding"]


def update(user_id, document_id, **values):
    names, vals, clauses = {}, {}, []
    for i, (key, value) in enumerate(values.items()):
        names[f"#k{i}"] = key
        vals[f":v{i}"] = value
        clauses.append(f"#k{i} = :v{i}")
    documents.update_item(
        Key={"userId": user_id, "documentId": document_id},
        UpdateExpression="SET " + ", ".join(clauses),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=vals,
    )


def handler(event, _context):
    records = event.get("Records", [])
    if event.get("source") == "aws.s3":
        records = [{"eventBridgeKey": event["detail"]["object"]["key"]}]
    for record in records:
        key = record.get("eventBridgeKey") or record["s3"]["object"]["key"]
        parts = key.split("/")
        if len(parts) < 4 or parts[0] != "documents":
            continue
        document_id = parts[2]
        # documentId is globally unique and indexed to resolve its owning user.
        result = documents.query(
            IndexName="DocumentIdIndex",
            KeyConditionExpression="documentId = :d",
            ExpressionAttributeValues={":d": document_id},
            Limit=1,
        )
        if not result.get("Items"):
            continue
        item = result["Items"][0]
        user_id = item["userId"]
        now = datetime.now(timezone.utc).isoformat()
        update(user_id, document_id, status="PROCESSING", updatedAt=now)
        try:
            raw = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            text = extract_text(raw, key)
            if not text.strip():
                raise ValueError("No extractable text was found. Scanned PDFs need OCR first.")
            chunks = split_text(text)
            matrix = np.asarray([embedding(chunk) for chunk in chunks], dtype=np.float32)
            vector_buffer = io.BytesIO()
            np.save(vector_buffer, matrix, allow_pickle=False)
            index_prefix = f"indexes/{parts[1]}/{document_id}"
            vector_key = f"{index_prefix}/vectors.npy"
            chunks_key = f"{index_prefix}/chunks.json"
            s3.put_object(Bucket=BUCKET, Key=vector_key, Body=vector_buffer.getvalue(), ContentType="application/octet-stream")
            s3.put_object(Bucket=BUCKET, Key=chunks_key, Body=json.dumps(chunks).encode(), ContentType="application/json")
            update(user_id, document_id, status="READY", vectorKey=vector_key, chunksKey=chunks_key, chunkCount=len(chunks), embeddingDimensions=EMBEDDING_DIMENSIONS, updatedAt=now)
        except Exception as exc:
            print(f"vectorization failed for {key}: {exc}")
            update(user_id, document_id, status="FAILED", errorMessage=str(exc)[:500], updatedAt=now)
    return {"processed": len(records)}
