"""
DynamoDB 권한 스모크 테스트 (Lambda 콘솔에서 실행).

목적:
  capstone-l3k1-lambda-role에 부여된 7종 DynamoDB 권한이
  fg-blocklist / fg-allowlist 두 테이블에 대해 실제 동작하는지 검증.

실행 방법:
  1. AWS Lambda 콘솔에서 신규 함수 생성
       - 함수명: fg-dynamodb-smoke-test (임의)
       - 런타임: Python 3.12 (또는 3.13/3.14)
       - 실행 역할: 기존 역할 사용 -> capstone-l3k1-lambda-role
       - 타임아웃: 30초로 변경 (기본 3초로는 부족)
  2. 이 파일 내용 전체를 lambda_function.py 에디터에 붙여넣기 후 Deploy
  3. Test 탭에서 새 이벤트(빈 {}) 생성 후 Invoke
  4. 응답 또는 CloudWatch Logs에서 각 액션이 OK 인지 확인
  5. 검증 끝나면 함수 삭제하거나 회귀 확인용으로 보존

검증 액션 (신청한 7종):
  PutItem, GetItem, UpdateItem, Query,
  BatchWriteItem, BatchGetItem, DeleteItem

테스트 데이터는 PK=class_id="SMOKE_TEST" 로 격리되므로
운영 데이터(GLOBAL)와 섞이지 않으며 마지막에 전부 삭제됨.
"""
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from datetime import datetime, timezone

REGION = "ap-northeast-2"
TABLES = ["fg-blocklist", "fg-allowlist"]
TEST_CLASS_ID = "SMOKE_TEST"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
ddb_client = dynamodb.meta.client


def _now():
    return datetime.now(timezone.utc).isoformat()


def smoke_test_table(table_name):
    table = dynamodb.Table(table_name)
    results = {}

    # 1) PutItem
    table.put_item(Item={
        "class_id": TEST_CLASS_ID,
        "sk": "process#smoke.exe",
        "enabled": True,
        "added_by": "smoke-test",
        "added_at": _now(),
    })
    results["PutItem"] = "OK"

    # 2) GetItem
    resp = table.get_item(
        Key={"class_id": TEST_CLASS_ID, "sk": "process#smoke.exe"},
        ConsistentRead=True,
    )
    assert "Item" in resp, "GetItem returned no Item"
    results["GetItem"] = "OK"

    # 3) UpdateItem
    table.update_item(
        Key={"class_id": TEST_CLASS_ID, "sk": "process#smoke.exe"},
        UpdateExpression="SET enabled = :v",
        ExpressionAttributeValues={":v": False},
    )
    results["UpdateItem"] = "OK"

    # 4) Query (PK 기준)
    resp = table.query(
        KeyConditionExpression=Key("class_id").eq(TEST_CLASS_ID),
        ConsistentRead=True,
    )
    assert resp["Count"] >= 1, f"Query returned {resp['Count']} items"
    results["Query"] = f"OK ({resp['Count']} items)"

    # 5) BatchWriteItem (2건 추가)
    with table.batch_writer() as batch:
        batch.put_item(Item={
            "class_id": TEST_CLASS_ID,
            "sk": "url#smoke1.example.com",
            "enabled": True,
            "added_by": "smoke-test",
            "added_at": _now(),
        })
        batch.put_item(Item={
            "class_id": TEST_CLASS_ID,
            "sk": "url#smoke2.example.com",
            "enabled": True,
            "added_by": "smoke-test",
            "added_at": _now(),
        })
    results["BatchWriteItem"] = "OK (2 puts)"

    # 6) BatchGetItem
    resp = ddb_client.batch_get_item(RequestItems={
        table_name: {
            "Keys": [
                {"class_id": TEST_CLASS_ID, "sk": "url#smoke1.example.com"},
                {"class_id": TEST_CLASS_ID, "sk": "url#smoke2.example.com"},
            ],
            "ConsistentRead": True,
        }
    })
    found = len(resp["Responses"].get(table_name, []))
    assert found == 2, f"BatchGetItem returned {found} items (expected 2)"
    results["BatchGetItem"] = f"OK ({found} items)"

    # 7) DeleteItem
    table.delete_item(Key={
        "class_id": TEST_CLASS_ID,
        "sk": "process#smoke.exe",
    })
    results["DeleteItem"] = "OK"

    # 잔여 데이터 정리 (BatchWriteItem - Delete)
    with table.batch_writer() as batch:
        batch.delete_item(Key={
            "class_id": TEST_CLASS_ID,
            "sk": "url#smoke1.example.com",
        })
        batch.delete_item(Key={
            "class_id": TEST_CLASS_ID,
            "sk": "url#smoke2.example.com",
        })

    return results


def lambda_handler(event, context):
    summary = {}
    for table_name in TABLES:
        try:
            summary[table_name] = smoke_test_table(table_name)
            print(f"[{table_name}] all 7 actions OK")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            summary[table_name] = {"ERROR": code, "message": msg}
            print(f"[{table_name}] FAILED: {code} - {msg}")
        except Exception as e:
            summary[table_name] = {"ERROR": type(e).__name__, "message": str(e)}
            print(f"[{table_name}] FAILED: {type(e).__name__} - {e}")

    print("SUMMARY:", summary)
    return summary
