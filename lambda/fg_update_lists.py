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

LIST_MAP = {
    "process_blacklist": ("data/blacklists.json", "process"),
    "title_blacklist":   ("data/blacklists.json", "title"),
    "url_blacklist":     ("data/blacklists.json", "url"),
    "content_keywords":  ("data/blacklists.json", "content_keywords"),
    "process_whitelist": ("data/whitelists.json", "process"),
    "url_whitelist":     ("data/whitelists.json", "url"),
}


def _get_json(key: str) -> dict:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "AccessDenied"):
            return {}
        raise


def _put_json(key: str, data: dict) -> None:
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _http_method(event: dict) -> str:
    return (event.get("httpMethod")
            or event.get("requestContext", {}).get("http", {}).get("method", "GET"))


def lambda_handler(event, context):
    if _http_method(event) == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
        action    = body.get("action")       # "add" | "remove" | "edit"
        list_type = body.get("list_type", "")
        entry     = body.get("entry", "").strip()

        if list_type not in LIST_MAP:
            return {"statusCode": 400, "headers": HEADERS,
                    "body": json.dumps({"error": "잘못된 목록 유형"})}

        s3_key, json_key = LIST_MAP[list_type]
        data = _get_json(s3_key)
        lst  = data.setdefault(json_key, [])

        if action == "add":
            if entry and entry not in lst:
                lst.append(entry)
        elif action == "remove":
            data[json_key] = [e for e in lst if e != entry]
        elif action == "edit":
            old = body.get("old_entry", "").strip()
            new = body.get("new_entry", "").strip()
            if not old or not new:
                return {"statusCode": 400, "headers": HEADERS,
                        "body": json.dumps({"error": "항목이 비어 있습니다"})}
            data[json_key] = [new if e == old else e for e in lst]
        else:
            return {"statusCode": 400, "headers": HEADERS,
                    "body": json.dumps({"error": "알 수 없는 action"})}

        _put_json(s3_key, data)
        return {"statusCode": 200, "headers": HEADERS,
                "body": json.dumps({"success": True})}
    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e)})}
