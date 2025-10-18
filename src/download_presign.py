import json
from typing import Any, Dict, List

import boto3

REGION = "us-east-1"
# Downstream UIs only surface objects inside these prefixes, so map folders to the
# specific bucket/prefix pair each download icon should reach.
FOLDER_CONFIG = {
    "summaries": {"bucket": "genai-out-use1-x7p5f0", "prefix": "summaries/"},
    "translations": {"bucket": "genai-out-use1-x7p5f0", "prefix": "translations/"},
    "errors": {"bucket": "genai-out-use1-x7p5f0", "prefix": "errors/"},
}
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS,DELETE",
}

s3 = boto3.client("s3", region_name=REGION)


def _response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload),
    }


def _list_files(config: Dict[str, str]) -> List[Dict[str, Any]]:
    """Return files (newest first) for the given prefix; used to populate the UI lists."""
    bucket = config["bucket"]
    prefix = config["prefix"]

    continuation = None
    contents = []

    while True:
        # Paginate through S3 listings so large folders don't break the UI.
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
        language = None
        display_name = filename
        if prefix.rstrip("/") == "translations":
            lang_part, sep, remainder = filename.partition("/")
            if sep and remainder:
                language = lang_part
                display_name = remainder
        entries.append(
            (
                timestamp,
                {
                    "key": key,
                    "filename": filename,
                    "display": display_name if display_name != filename else None,
                    "language": language,
                    "size": obj.get("Size", 0),
                    "last_modified": last_modified.isoformat() if last_modified else None,
                },
            )
        )

    # Show newest files first so fresh outputs float to the top of the dashboard.
    entries.sort(key=lambda item: item[0], reverse=True)
    return [entry[1] for entry in entries]


def _sanitize_filename(filename: str) -> str:
    # Strip leading slashes and reject traversal patterns to keep keys in-bucket.
    sanitized = filename.lstrip("/")
    if not sanitized:
        raise ValueError("Invalid filename")

    parts = sanitized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid filename")

    return sanitized


def _get_method(event: Dict[str, Any]) -> str:
    method = event.get("httpMethod")
    if not method:
        method = event.get("requestContext", {}).get("http", {}).get("method")
    return (method or "GET").upper()


def lambda_handler(event, context):
    method = _get_method(event)

    if method == "OPTIONS":
        return _response(200, {"message": "ok"})

    params = event.get("queryStringParameters") or {}
    filename = params.get("filename")
    folder = params.get("folder")
    # Allow browsers to request a listing for the summary/translation columns.
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

    if method == "DELETE":
        if not filename:
            return _response(400, {"error": "Missing filename"})
        try:
            sanitized = _sanitize_filename(filename)
        except ValueError as exc:
            return _response(400, {"error": str(exc)})

        prefix = config["prefix"]
        key = sanitized if sanitized.startswith(prefix) else f"{prefix}{sanitized}"

        try:
            # Allow the UI to tidy generated files without exposing S3 credentials.
            s3.delete_object(Bucket=config["bucket"], Key=key)
        except s3.exceptions.NoSuchKey:
            return _response(404, {"error": "File not found"})
        except Exception as exc:
            return _response(500, {"error": str(exc)})

        return _response(200, {"deleted": key})

    if method != "GET":
        return _response(405, {"error": "Unsupported method"})

    if not filename:
        return _response(400, {"error": "Missing filename"})

    try:
        sanitized = _sanitize_filename(filename)
    except ValueError as exc:
        return _response(400, {"error": str(exc)})

    prefix = config["prefix"]
    if sanitized.startswith(prefix):
        key = sanitized
    else:
        key = f"{prefix}{sanitized}"

    try:
        # Issue a one-hour GET URL so the browser can download the artefact directly.
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": config["bucket"], "Key": key},
            ExpiresIn=3600,
        )
    except Exception as exc:
        return _response(500, {"error": str(exc)})

    return _response(200, {"url": url})
