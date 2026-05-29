"""
DynamoDB 시드 스크립트 (API Gateway 경유 버전).

본인 자격증명에 dynamodb:BatchWriteItem Explicit Deny가 부착되어 있어
직접 적재가 영구 불가하므로, fg-update-lists Lambda(action="bulk_add")를
API Gateway POST /list/update 라우트로 호출하여 적재한다.

전제:
- fg-update-lists가 DynamoDB 기반 + bulk_add 지원으로 배포되어 있어야 함
- API Gateway focusguard-api-v2의 POST /list/update 라우트가 활성 상태여야 함
- urllib.request만 사용 → 외부 의존 없음

사용 예시:
    # 1) dry-run으로 적재 항목 미리보기
    python scripts/seed_dynamodb.py --dry-run

    # 2) CLI 인자로 URL 전달
    python scripts/seed_dynamodb.py \
        --api-url https://<api-id>.execute-api.ap-northeast-2.amazonaws.com/<stage>/list/update

    # 3) 환경변수로 URL 전달 (.env 또는 셸에서)
    set FG_LIST_UPDATE_URL=https://...
    python scripts/seed_dynamodb.py

    # 4) API Key 인증이 걸려있는 경우
    python scripts/seed_dynamodb.py --api-key <key>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_dotenv(path: Path) -> None:
    """간이 .env 로더 — 의존성 없이 KEY=VALUE 라인만 os.environ에 주입."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")

ADDED_BY = "seed-script"
REASON = "Phase 1 YAML 초기 이관"

# YAML 키 → fg-update-list의 list_type 값
BLOCK_MAP = {
    "process":          "process_blacklist",
    "title":            "title_blacklist",
    "url":              "url_blacklist",
    "content_keywords": "content_keywords",
}
ALLOW_MAP = {
    "process": "process_whitelist",
    "url":     "url_whitelist",
}


def load_yaml(path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_items(data, type_map):
    items = []
    for yaml_key, list_type in type_map.items():
        for value in (data.get(yaml_key) or []):
            items.append({"list_type": list_type, "entry": value})
    return items


def post_bulk(url, items, api_key=None, timeout=30):
    payload = {
        "action":   "bulk_add",
        "added_by": ADDED_BY,
        "reason":   REASON,
        "items":    items,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.environ.get("FG_LIST_UPDATE_URL"),
        help="POST /list/update 엔드포인트 URL (또는 환경변수 FG_LIST_UPDATE_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FG_API_KEY"),
        help="API Gateway API Key (필요 시, 또는 환경변수 FG_API_KEY)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=100,
        help="청크당 항목 수 (기본 100, Lambda 페이로드 한도·타임아웃 안전선)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="실제 호출 없이 적재 예정 항목 수와 청크 분할만 출력",
    )
    args = parser.parse_args()

    block_items = build_items(load_yaml(DATA / "blacklists.yaml"), BLOCK_MAP)
    allow_items = build_items(load_yaml(DATA / "whitelists.yaml"), ALLOW_MAP)
    all_items = block_items + allow_items

    n_chunks = (len(all_items) + args.chunk_size - 1) // max(args.chunk_size, 1)
    print(f"fg-blocklist 적재 예정: {len(block_items)}개")
    print(f"fg-allowlist 적재 예정: {len(allow_items)}개")
    print(f"전체: {len(all_items)}개 / 청크 크기 {args.chunk_size} / 청크 수 {n_chunks}")

    if args.dry_run:
        print("\n--- DRY RUN 미리보기 (처음 5개) ---")
        for it in all_items[:5]:
            print(it)
        return 0

    if not args.api_url:
        print("ERROR: --api-url 또는 환경변수 FG_LIST_UPDATE_URL이 필요합니다", file=sys.stderr)
        return 2

    total_block = 0
    total_allow = 0
    for idx, chunk in enumerate(chunked(all_items, args.chunk_size), 1):
        status, body = post_bulk(args.api_url, chunk, api_key=args.api_key)
        preview = body[:300] + ("..." if len(body) > 300 else "")
        print(f"[chunk {idx}/{n_chunks}] HTTP {status} | items={len(chunk)} | resp={preview}")
        if status != 200:
            print("FAIL: 청크 적재 실패 — 중단합니다.", file=sys.stderr)
            return 1
        try:
            written = json.loads(body).get("written", {})
            total_block += written.get("fg-blocklist", 0)
            total_allow += written.get("fg-allowlist", 0)
        except json.JSONDecodeError:
            pass

    print(f"\n적재 완료 - fg-blocklist {total_block}건, fg-allowlist {total_allow}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
