"""
fg-get-list Lambda (DynamoDB 버전).

라우트: GET /list (라우트 추가는 ③번 작업에서 진행)
역할: fg-blocklist / fg-allowlist 전체 항목 조회.

응답 body 형식 (기존 fg-get-list S3 버전과 동일):
  {
    "blacklists": {
      "process": [...], "title": [...], "url": [...], "content_keywords": [...]
    },
    "whitelists": {
      "process": [...], "url": [...]
    }
  }

규칙:
- enabled=true 항목만 포함 (소프트 비활성 항목은 응답 제외)
- 메타데이터(added_by/added_at/reason)는 응답에서 제외 (필요 시 추후 ?include_meta=true)
- SK prefix → 응답 JSON 키 매핑에서 content_keyword(단수) -> content_keywords(복수)로 변환

환경변수 (전부 기본값 있음):
  BLOCKLIST_TABLE  default: fg-blocklist
  ALLOWLIST_TABLE  default: fg-allowlist
  CLASS_ID         default: GLOBAL
"""
import json
import os

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
BLOCKLIST_TABLE = os.environ.get("BLOCKLIST_TABLE", "fg-blocklist")
ALLOWLIST_TABLE = os.environ.get("ALLOWLIST_TABLE", "fg-allowlist")
CLASS_ID = os.environ.get("CLASS_ID", "GLOBAL")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
block_table = dynamodb.Table(BLOCKLIST_TABLE)
allow_table = dynamodb.Table(ALLOWLIST_TABLE)

HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}

BLOCK_PREFIX_TO_KEY = {
    "process": "process",
    "title": "title",
    "url": "url",
    "content_keyword": "content_keywords",  # 단수 -> 복수
}
ALLOW_PREFIX_TO_KEY = {
    "process": "process",
    "url": "url",
}


def _http_method(event):
    return (event.get("httpMethod")
            or event.get("requestContext", {}).get("http", {}).get("method", "GET"))


def _query_all(table):
    """class_id 단일 PK의 모든 아이템을 페이지네이션 포함해 반환."""
    items = []
    kwargs = {"KeyConditionExpression": Key("class_id").eq(CLASS_ID)}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def _group(items, prefix_to_key):
    out = {key: [] for key in prefix_to_key.values()}
    for it in items:
        if not it.get("enabled", True):
            continue
        sk = it.get("sk", "")
        prefix, _, value = sk.partition("#")
        key = prefix_to_key.get(prefix)
        if not key or not value:
            continue
        out[key].append(value)
    return out


def lambda_handler(event, context):
    if _http_method(event) == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    try:
        block_items = _query_all(block_table)
        allow_items = _query_all(allow_table)
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({
                "blacklists": _group(block_items, BLOCK_PREFIX_TO_KEY),
                "whitelists": _group(allow_items, ALLOW_PREFIX_TO_KEY),
            }, ensure_ascii=False),
        }
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        return {
            "statusCode": 500,
            "headers": HEADERS,
            "body": json.dumps({"error": f"{code}: {msg}"}, ensure_ascii=False),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": HEADERS,
            "body": json.dumps({"error": str(e)}, ensure_ascii=False),
        }
