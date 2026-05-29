import json
import boto3
import os
from datetime import datetime, timezone
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
BUCKET = os.environ["DATA_BUCKET"]

HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}


def _http_method(event: dict) -> str:
    return (event.get("httpMethod")
            or event.get("requestContext", {}).get("http", {}).get("method", "GET"))


def lambda_handler(event, context):
    if _http_method(event) == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key   = f"events/{today}.jsonl"

        try:
            existing = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "AccessDenied"):
                existing = ""
            else:
                raise

        new_line = json.dumps(body, ensure_ascii=False) + "\n"
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=(existing + new_line).encode("utf-8"),
            ContentType="application/x-ndjson",
        )
        return {"statusCode": 200, "headers": HEADERS,
                "body": json.dumps({"success": True})}
    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e)})}
