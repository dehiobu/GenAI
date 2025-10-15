import json
import boto3

REGION = "us-east-1"
BUCKET = "genai-in-use1-x7p5f0"
# Objects must land under incoming/ for the processing Lambda trigger to fire.
UPLOAD_PREFIX = "incoming/"

s3 = boto3.client("s3", region_name=REGION)


def lambda_handler(event, context):
    # Guard against missing query params when invoked via API Gateway.
    params = event.get("queryStringParameters") or {}
    filename = params.get("filename")

    if not filename:
        return {
            "statusCode": 400,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "missing filename"}),
        }

    # Force uploads into the incoming/ prefix so downstream processing finds them.
    normalized = filename.lstrip("/")
    if not normalized.startswith(UPLOAD_PREFIX):
        key = f"{UPLOAD_PREFIX}{normalized}"
    else:
        key = normalized

    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=3600,
    )

    return {
        # Allow browsers to call this endpoint from any origin.
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"url": url, "bucket": BUCKET, "key": key}),
    }
