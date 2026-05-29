import json
import boto3
import os
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("UNLOCK_TABLE", "fg-unlock-requests"))

HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}


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
        path_device_id = path.rstrip("/").split("/")[-1]

        # GET /unlock/{device_id} — 학생 PC 폴링: 승인 여부 확인
        if method == "GET" and path_device_id not in ("unlock", ""):
            device_id = path_device_id
            resp = table.get_item(Key={"device_id": device_id})
            item = resp.get("Item")
            if item and item.get("status") == "approved":
                table.update_item(
                    Key={"device_id": device_id},
                    UpdateExpression="SET #s = :s",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "consumed"},
                )
                return {"statusCode": 200, "headers": HEADERS,
                        "body": json.dumps({"status": "approved"})}
            status = item.get("status", "none") if item else "none"
            return {"statusCode": 200, "headers": HEADERS,
                    "body": json.dumps({"status": status})}

        # GET /unlock — Admin: pending 목록 조회
        if method == "GET":
            resp = table.scan(FilterExpression=Attr("status").eq("pending"))
            pending = resp.get("Items", [])
            return {"statusCode": 200, "headers": HEADERS,
                    "body": json.dumps({"pending": pending}, ensure_ascii=False)}

        body      = json.loads(event.get("body") or "{}")
        action    = body.get("action")
        device_id = body.get("device_id", "").strip()

        # POST action=request — 학생 PC: 해제 요청 생성
        if action == "request":
            table.put_item(Item={
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
            table.update_item(
                Key={"device_id": device_id},
                UpdateExpression="SET #s = :s, approved_at = :t",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "approved",
                    ":t": datetime.now(timezone.utc).isoformat(),
                },
            )
            return {"statusCode": 200, "headers": HEADERS,
                    "body": json.dumps({"success": True})}

        return {"statusCode": 400, "headers": HEADERS,
                "body": json.dumps({"error": "알 수 없는 요청"})}

    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e)})}
