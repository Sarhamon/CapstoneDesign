"""
DynamoDB 시드 스크립트
data/blacklists.yaml + data/whitelists.yaml을 fg-blocklist / fg-allowlist에 적재한다.

전제:
- 본인 AWS 자격증명(콘솔 로그인과 동일한 사용자)에 두 테이블 PutItem 권한이 있어야 함
- Lambda 실행 역할 권한과는 별개 — 이 스크립트는 사용자 자격증명으로 직접 호출

사용 예시:
    python scripts/seed_dynamodb.py --dry-run
    python scripts/seed_dynamodb.py
    python scripts/seed_dynamodb.py --profile myprofile
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import boto3
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CLASS_ID = "GLOBAL"
ADDED_BY = "seed-script"
REASON = "Phase 1 YAML 초기 이관"
KST = timezone(timedelta(hours=9))

# YAML은 복수형 content_keywords, DynamoDB SK는 단수형 content_keyword로 통일
BLOCK_MAP = {
    "process": "process",
    "title": "title",
    "url": "url",
    "content_keywords": "content_keyword",
}
ALLOW_MAP = {
    "process": "process",
    "url": "url",
}


def load_yaml(path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_items(data, type_map):
    now = datetime.now(KST).isoformat(timespec="seconds")
    items = []
    for yaml_key, sk_prefix in type_map.items():
        for value in (data.get(yaml_key) or []):
            items.append({
                "class_id": CLASS_ID,
                "sk": f"{sk_prefix}#{value}",
                "enabled": True,
                "added_by": ADDED_BY,
                "added_at": now,
                "reason": REASON,
            })
    return items


def write_items(table, items):
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="ap-northeast-2")
    parser.add_argument("--profile", default=None, help="AWS profile name (없으면 기본 자격증명)")
    parser.add_argument("--dry-run", action="store_true", help="실제 쓰기 없이 항목 수와 샘플만 출력")
    args = parser.parse_args()

    block_items = build_items(load_yaml(DATA / "blacklists.yaml"), BLOCK_MAP)
    allow_items = build_items(load_yaml(DATA / "whitelists.yaml"), ALLOW_MAP)

    print(f"fg-blocklist 적재 예정: {len(block_items)}개")
    print(f"fg-allowlist 적재 예정: {len(allow_items)}개")

    if args.dry_run:
        print("\n--- DRY RUN 미리보기 (각 테이블 처음 3개) ---")
        for item in block_items[:3] + allow_items[:3]:
            print(item)
        return 0

    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    dynamo = session.resource("dynamodb", region_name=args.region)

    write_items(dynamo.Table("fg-blocklist"), block_items)
    print(f"fg-blocklist 적재 완료: {len(block_items)}개")

    write_items(dynamo.Table("fg-allowlist"), allow_items)
    print(f"fg-allowlist 적재 완료: {len(allow_items)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
