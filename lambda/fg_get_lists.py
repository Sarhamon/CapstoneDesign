import json
import boto3
import os
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
BUCKET = os.environ["DATA_BUCKET"]

HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}


def _get_json(key: str) -> dict:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "AccessDenied"):
            return {}
        raise


def _http_method(event: dict) -> str:
    return (event.get("httpMethod")
            or event.get("requestContext", {}).get("http", {}).get("method", "GET"))


def lambda_handler(event, context):
    if _http_method(event) == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    try:
        blacklists = _get_json("data/blacklists.json")
        whitelists = _get_json("data/whitelists.json")
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps(
                {"blacklists": blacklists, "whitelists": whitelists},
                ensure_ascii=False,
            ),
        }
    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e)})}
