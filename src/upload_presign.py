import json
import os
import re
from typing import Any, Dict

import boto3

REGION = "us-east-1"
BUCKET = "genai-in-use1-x7p5f0"
# Objects must land under incoming/ for the processing Lambda trigger to fire.
UPLOAD_PREFIX = "incoming/"
FALLBACK_TARGET_LANG = "fr"
DEFAULT_TARGET_LANG = os.environ.get("DEFAULT_TARGET_LANG", FALLBACK_TARGET_LANG)
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$")
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}

s3 = boto3.client("s3", region_name=REGION)


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status_code, "headers": CORS_HEADERS, "body": json.dumps(body)}


def _normalize_language(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("missing language")
    if not LANGUAGE_PATTERN.fullmatch(cleaned):
        raise ValueError("invalid language")

    parts = cleaned.split("-", 1)
    if len(parts) == 1:
        return parts[0].lower()

    primary, region = parts
    return f"{primary.lower()}-{region.upper()}"


def lambda_handler(event, context):
    # Short-circuit browser preflight checks so real requests can follow.
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"message": "ok"})

    params = event.get("queryStringParameters") or {}
    filename = params.get("filename")

    if not filename:
        return _response(400, {"error": "missing filename"})

    # Strip leading slashes to keep keys predictable and prevent directory traversal.
    normalized = filename.lstrip("/")
    if not normalized:
        return _response(400, {"error": "invalid filename"})
    if "/" in normalized or ".." in normalized.split("/"):
        return _response(400, {"error": "invalid filename"})

    lang_param = params.get("lang") or params.get("targetLang")
    try:
        target_lang = _normalize_language(lang_param if lang_param else DEFAULT_TARGET_LANG)
    except ValueError as exc:
        if lang_param:
            return _response(400, {"error": str(exc)})
        target_lang = _normalize_language(FALLBACK_TARGET_LANG)

    content_type = params.get("contentType")
    if content_type:
        content_type = content_type.strip()
        if not content_type:
            content_type = None

    lang_prefix = f"{UPLOAD_PREFIX}{target_lang}/"
    if normalized.startswith(UPLOAD_PREFIX):
        key = normalized
    else:
        key = f"{lang_prefix}{normalized}"

    try:
        presign_params = {"Bucket": BUCKET, "Key": key}
        if content_type:
            presign_params["ContentType"] = content_type

        # Build a time-limited PUT URL so the browser can upload straight to S3.
        # Build a time-limited PUT URL so the browser can upload straight to S3.
        url = s3.generate_presigned_url(
            "put_object",
            Params=presign_params,
            ExpiresIn=3600,
            HttpMethod="PUT",
        )
    except Exception as exc:
        return _response(500, {"error": str(exc)})


    # Return presign metadata so the front-end knows where to upload.
    body: Dict[str, Any] = {"url": url, "bucket": BUCKET, "key": key, "targetLang": target_lang}
    if content_type:
        body["contentType"] = content_type

    return _response(200, body)
