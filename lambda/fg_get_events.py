import json
import boto3
import os
from datetime import datetime, timezone, timedelta
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
        params = event.get("queryStringParameters") or {}
        limit = min(int(params.get("limit", 100)), 500)
        days  = min(int(params.get("days", 3)), 30)

        events = []
        for i in range(days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            try:
                obj   = s3.get_object(Bucket=BUCKET, Key=f"events/{date}.jsonl")
                lines = obj["Body"].read().decode("utf-8").strip().split("\n")
                for line in reversed(lines):
                    if line.strip():
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                    if len(events) >= limit:
                        break
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("NoSuchKey", "AccessDenied"):
                    raise
            if len(events) >= limit:
                break

        return {"statusCode": 200, "headers": HEADERS,
                "body": json.dumps({"events": events[:limit]}, ensure_ascii=False)}
    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e)})}
