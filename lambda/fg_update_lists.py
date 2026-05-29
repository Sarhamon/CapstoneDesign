"""
fg-update-lists Lambda (DynamoDB 버전).

라우트: POST /list/update
역할: fg-blocklist / fg-allowlist 테이블의 단건 CRUD + 배치 적재.

요청 body 형식:
  단건 add/remove:
    { "action": "add"|"remove", "list_type": "<type>", "entry": "<value>" }
  단건 edit (이름 변경):
    { "action": "edit", "list_type": "<type>",
      "old_entry": "<old>", "new_entry": "<new>" }
  배치 적재 (seed 스크립트가 API 경유로 호출):
    { "action": "bulk_add",
      "items": [ {"list_type": "<type>", "entry": "<value>"}, ... ] }

list_type 매핑:
  process_blacklist  -> fg-blocklist, SK prefix "process"
  title_blacklist    -> fg-blocklist, SK prefix "title"
  url_blacklist      -> fg-blocklist, SK prefix "url"
  content_keywords   -> fg-blocklist, SK prefix "content_keyword"
  process_whitelist  -> fg-allowlist, SK prefix "process"
  url_whitelist      -> fg-allowlist, SK prefix "url"

환경변수 (전부 기본값 있음):
  BLOCKLIST_TABLE  default: fg-blocklist
  ALLOWLIST_TABLE  default: fg-allowlist
  CLASS_ID         default: GLOBAL
"""
import json
import os
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
BLOCKLIST_TABLE = os.environ.get("BLOCKLIST_TABLE", "fg-blocklist")
ALLOWLIST_TABLE = os.environ.get("ALLOWLIST_TABLE", "fg-allowlist")
CLASS_ID = os.environ.get("CLASS_ID", "GLOBAL")
KST = timezone(timedelta(hours=9))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
block_table = dynamodb.Table(BLOCKLIST_TABLE)
allow_table = dynamodb.Table(ALLOWLIST_TABLE)

HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}

LIST_MAP = {
    "process_blacklist": (block_table, "process"),
    "title_blacklist":   (block_table, "title"),
    "url_blacklist":     (block_table, "url"),
    "content_keywords":  (block_table, "content_keyword"),
    "process_whitelist": (allow_table, "process"),
    "url_whitelist":     (allow_table, "url"),
}


def _now():
    return datetime.now(KST).isoformat(timespec="seconds")


def _http_method(event):
    return (event.get("httpMethod")
            or event.get("requestContext", {}).get("http", {}).get("method", "POST"))


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": HEADERS,
        "body": json.dumps(body, ensure_ascii=False),
    }


def _put(table, sk_prefix, entry, added_by, reason=None):
    item = {
        "class_id": CLASS_ID,
        "sk": f"{sk_prefix}#{entry}",
        "enabled": True,
        "added_by": added_by,
        "added_at": _now(),
    }
    if reason:
        item["reason"] = reason
    table.put_item(Item=item)


def _delete(table, sk_prefix, entry):
    table.delete_item(Key={
        "class_id": CLASS_ID,
        "sk": f"{sk_prefix}#{entry}",
    })


def _handle_single(body):
    action = body.get("action")
    list_type = body.get("list_type", "")
    entry = (body.get("entry") or "").strip()
    added_by = body.get("added_by") or "admin"
    reason = body.get("reason")

    if list_type not in LIST_MAP:
        return _resp(400, {"error": "잘못된 list_type"})

    table, sk_prefix = LIST_MAP[list_type]

    if action == "add":
        if not entry:
            return _resp(400, {"error": "entry가 비어 있습니다"})
        _put(table, sk_prefix, entry, added_by, reason)

    elif action == "remove":
        if not entry:
            return _resp(400, {"error": "entry가 비어 있습니다"})
        _delete(table, sk_prefix, entry)

    elif action == "edit":
        old = (body.get("old_entry") or "").strip()
        new = (body.get("new_entry") or "").strip()
        if not old or not new:
            return _resp(400, {"error": "old_entry/new_entry가 비어 있습니다"})
        _delete(table, sk_prefix, old)
        _put(table, sk_prefix, new, added_by, reason)

    else:
        return _resp(400, {"error": "알 수 없는 action"})

    return _resp(200, {"success": True})


def _handle_bulk(body):
    items = body.get("items") or []
    added_by = body.get("added_by") or "seed-script"
    reason = body.get("reason")

    if not isinstance(items, list) or not items:
        return _resp(400, {"error": "items 배열이 비어 있습니다"})

    grouped = {BLOCKLIST_TABLE: [], ALLOWLIST_TABLE: []}
    invalid = []
    now = _now()

    for idx, it in enumerate(items):
        lt = it.get("list_type", "")
        entry = (it.get("entry") or "").strip()
        if lt not in LIST_MAP or not entry:
            invalid.append({"index": idx, "list_type": lt, "entry": entry})
            continue
        table, sk_prefix = LIST_MAP[lt]
        item = {
            "class_id": CLASS_ID,
            "sk": f"{sk_prefix}#{entry}",
            "enabled": True,
            "added_by": added_by,
            "added_at": now,
        }
        if reason:
            item["reason"] = reason
        grouped[table.name].append(item)

    if invalid:
        return _resp(400, {
            "error": "유효하지 않은 항목이 포함됨 (트랜잭션 전체 거부)",
            "invalid": invalid[:20],
            "invalid_count": len(invalid),
        })

    written = {}
    for table_name, batch_items in grouped.items():
        if not batch_items:
            continue
        table = dynamodb.Table(table_name)
        with table.batch_writer() as bw:
            for item in batch_items:
                bw.put_item(Item=item)
        written[table_name] = len(batch_items)

    return _resp(200, {"success": True, "written": written})


def lambda_handler(event, context):
    if _http_method(event) == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
        if body.get("action") == "bulk_add":
            return _handle_bulk(body)
        return _handle_single(body)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        return _resp(500, {"error": f"{code}: {msg}"})
    except Exception as e:
        return _resp(500, {"error": str(e)})
