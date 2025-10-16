import json
from typing import Any, Dict, List

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


def _list_files(config: Dict[str, str]) -> List[Dict[str, Any]]:
    bucket = config["bucket"]
    prefix = config["prefix"]

    continuation = None
    contents = []

    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        page = s3.list_objects_v2(**kwargs)
        contents.extend(page.get("Contents", []))

        if not page.get("IsTruncated"):
            break
        continuation = page.get("NextContinuationToken")

    entries = []
    for obj in contents:
        key = obj["Key"]
        if key.endswith("/"):
            continue

        filename = key[len(prefix) :]
        last_modified = obj.get("LastModified")
        timestamp = last_modified.timestamp() if last_modified else 0.0
        entries.append(
            (
                timestamp,
                {
                    "key": key,
                    "filename": filename,
                    "size": obj.get("Size", 0),
                    "last_modified": last_modified.isoformat() if last_modified else None,
                },
            )
        )

    entries.sort(key=lambda item: item[0], reverse=True)
    return [entry[1] for entry in entries]


def lambda_handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"message": "ok"})

    params = event.get("queryStringParameters") or {}
    filename = params.get("filename")
    folder = params.get("folder")
    list_requested = str(params.get("list", "")).lower() in {"1", "true", "yes"}

    if not folder:
        return _response(400, {"error": "Missing folder"})

    config = FOLDER_CONFIG.get(folder)
    if not config:
        return _response(400, {"error": f"Unsupported folder '{folder}'"})

    if list_requested:
        try:
            files = _list_files(config)
        except Exception as exc:
            return _response(500, {"error": str(exc)})
        return _response(200, {"files": files})

    if not filename:
        return _response(400, {"error": "Missing filename"})

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
