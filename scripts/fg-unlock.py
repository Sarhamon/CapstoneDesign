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


def _key(device_id: str) -> str:
    return f"unlock/{device_id}.json"


def _get(device_id: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=_key(device_id))
        return json.loads(obj["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "AccessDenied"):
            return None
        raise


def _put(device_id: str, data: dict) -> None:
    s3.put_object(
        Bucket=BUCKET,
        Key=_key(device_id),
        Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


def _http_method(event: dict) -> str:
    return (event.get("httpMethod")
            or event.get("requestContext", {}).get("http", {}).get("method", "GET"))


def _path(event: dict) -> str:
    return event.get("path") or event.get("rawPath", "")


def lambda_handler(event, context):
    if _http_method(event) == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    method = _http_method(event)
    path   = _path(event)

    try:
        # GET /unlock/{device_id} — 학생 PC 폴링: 승인 여부 확인
        path_device_id = path.rstrip("/").split("/")[-1]
        if method == "GET" and path_device_id not in ("unlock", ""):
            device_id = path_device_id
            data = _get(device_id)
            if data and data.get("status") == "approved":
                _put(device_id, {**data, "status": "consumed"})
                return {"statusCode": 200, "headers": HEADERS,
                        "body": json.dumps({"status": "approved"})}
            status = data.get("status", "none") if data else "none"
            return {"statusCode": 200, "headers": HEADERS,
                    "body": json.dumps({"status": status})}

        # GET /unlock — Admin: pending 목록 전체 조회
        if method == "GET":
            paginator = s3.get_paginator("list_objects_v2")
            pending = []
            for page in paginator.paginate(Bucket=BUCKET, Prefix="unlock/"):
                for obj in page.get("Contents", []):
                    device_id = obj["Key"].removeprefix("unlock/").removesuffix(".json")
                    data = _get(device_id)
                    if data and data.get("status") == "pending":
                        pending.append(data)
            return {"statusCode": 200, "headers": HEADERS,
                    "body": json.dumps({"pending": pending}, ensure_ascii=False)}

        body      = json.loads(event.get("body") or "{}")
        action    = body.get("action")
        device_id = body.get("device_id", "").strip()

        # POST action=request — 학생 PC: 해제 요청 생성
        if action == "request":
            _put(device_id, {
                "device_id": device_id,
                "status": "pending",
                "reason": body.get("reason", ""),
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "approved_at": None,
            })
            return {"statusCode": 200, "headers": HEADERS,
                    "body": json.dumps({"success": True})}

        # POST action=approve — Admin: 해제 승인
        if action == "approve":
            data = _get(device_id) or {}
            data.update({"status": "approved",
                          "approved_at": datetime.now(timezone.utc).isoformat()})
            _put(device_id, data)
            return {"statusCode": 200, "headers": HEADERS,
                    "body": json.dumps({"success": True})}

        return {"statusCode": 400, "headers": HEADERS,
                "body": json.dumps({"error": "알 수 없는 요청"})}

    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e)})}
