import json
from typing import Any, Dict

import boto3

REGION = "us-east-1"
# Downstream UIs only surface objects inside these prefixes, so map folders to the
# specific bucket/prefix pair each download icon should reach.
FOLDER_CONFIG = {
    "summaries": {"bucket": "genai-out-use1-x7p5f0", "prefix": "summaries/"},
    "translations": {"bucket": "genai-out-use1-x7p5f0", "prefix": "translations/"},
}
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}

s3 = boto3.client("s3", region_name=REGION)


def _response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload),
    }


def lambda_handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"message": "ok"})

    params = event.get("queryStringParameters") or {}
    filename = params.get("filename")
    folder = params.get("folder")

    if not filename or not folder:
        return _response(400, {"error": "Missing filename or folder"})

    config = FOLDER_CONFIG.get(folder)
    if not config:
        return _response(400, {"error": f"Unsupported folder '{folder}'"})

    sanitized = filename.lstrip("/")
    if not sanitized:
        return _response(400, {"error": "Invalid filename"})

    parts = sanitized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return _response(400, {"error": "Invalid filename"})

    prefix = config["prefix"]
    if sanitized.startswith(prefix):
        key = sanitized
    else:
        key = f"{prefix}{sanitized}"

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": config["bucket"], "Key": key},
            ExpiresIn=3600,
        )
    except Exception as exc:
        return _response(500, {"error": str(exc)})

    return _response(200, {"url": url})
