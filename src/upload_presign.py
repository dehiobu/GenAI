import json
from typing import Any, Dict

import boto3

REGION = "us-east-1"
BUCKET = "genai-in-use1-x7p5f0"
# Objects must land under incoming/ for the processing Lambda trigger to fire.
UPLOAD_PREFIX = "incoming/"
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}

s3 = boto3.client("s3", region_name=REGION)


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status_code, "headers": CORS_HEADERS, "body": json.dumps(body)}


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

    content_type = params.get("contentType")
    if content_type:
        content_type = content_type.strip()
        if not content_type:
            content_type = None

    if not normalized.startswith(UPLOAD_PREFIX):
        key = f"{UPLOAD_PREFIX}{normalized}"
    else:
        key = normalized

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
    body: Dict[str, Any] = {"url": url, "bucket": BUCKET, "key": key}
    if content_type:
        body["contentType"] = content_type

    return _response(200, body)
