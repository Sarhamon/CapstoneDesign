"""
scripts/seed_dynamodb.py
blacklists.yaml + whitelists.yaml 전체를 DynamoDB에 업로드한다.
API Gateway → fg-update-lists Lambda 경유 (bulk_add).

사용법:
    python scripts/seed_dynamodb.py
    python scripts/seed_dynamodb.py --dry-run   # 실제 전송 없이 항목 수만 출력
"""

import argparse
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CLOUD_API_URL = os.environ.get("CLOUD_API_URL", "").rstrip("/")
ENDPOINT = f"{CLOUD_API_URL}/list/update"

LIST_MAP = {
    "process_blacklist": ("blacklists.yaml", "process"),
    "title_blacklist":   ("blacklists.yaml", "title"),
    "url_blacklist":     ("blacklists.yaml", "url"),
    "content_keywords":  ("blacklists.yaml", "content_keywords"),
    "process_whitelist": ("whitelists.yaml", "process"),
    "url_whitelist":     ("whitelists.yaml", "url"),
}


def load_yaml(filename: str) -> dict:
    path = BASE_DIR / "data" / filename
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_items() -> list[dict]:
    cache: dict[str, dict] = {}
    items = []
    for list_type, (filename, key) in LIST_MAP.items():
        if filename not in cache:
            cache[filename] = load_yaml(filename)
        entries = cache[filename].get(key, [])
        for entry in entries:
            items.append({"list_type": list_type, "entry": str(entry)})
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not CLOUD_API_URL:
        print("오류: .env에 CLOUD_API_URL이 설정되어 있지 않습니다.")
        sys.exit(1)

    items = build_items()
    print(f"업로드 항목 수: {len(items)}개  →  {ENDPOINT}")

    if args.dry_run:
        for it in items:
            print(f"  [{it['list_type']}] {it['entry']}")
        return

    payload = {
        "action": "bulk_add",
        "items": items,
        "added_by": "seed-script",
    }
    resp = requests.post(ENDPOINT, json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if result.get("success"):
        print(f"완료: {result.get('written', {})}")
    else:
        print(f"실패: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
