#!/usr/bin/env python3
"""对比游戏系列与 repo 已有系列，输出缺失的 expansion code。

用途：增量更新时自动发现需要同步的系列。
数据源：
  - 游戏系列：frida-test bridge packImages.raw {manifestOnly:true} 的 expansionId
  - repo 已有：images/<locale>/cards-by-set/ 目录名
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.bridge_client import BridgeSession  # noqa: E402

# 用作"repo 已有系列"判断的目录（zh-TW 是主语言，目录最全）
REFERENCE_LOCALE = "zh-TW"


def discover_game_expansions(bridge_url: str) -> list[str]:
    """从 bridge 拿游戏所有 pack，提取去重的 expansionId（已排序）。"""
    with BridgeSession(bridge_url) as session:
        archive_bytes = session.request(
            "ptcgp.packImages.raw", {"manifestOnly": True}
        )
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise RuntimeError("bridge archive missing manifest.json")
        manifest = json.loads(manifest_file.read())
    expansions = sorted({pack["expansionId"] for pack in manifest["packs"]})
    return expansions


def discover_repo_expansions(repo_root: Path, locale: str = REFERENCE_LOCALE) -> list[str]:
    """扫 images/<locale>/cards-by-set/ 目录名，返回已排序的 expansion code。"""
    sets_dir = repo_root / "images" / locale / "cards-by-set"
    if not sets_dir.is_dir():
        return []
    return sorted(p.name for p in sets_dir.iterdir() if p.is_dir())


def find_missing_expansions(game: list[str], repo: list[str]) -> list[str]:
    repo_set = set(repo)
    return [code for code in game if code not in repo_set]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="对比游戏与 repo 系列，输出缺失 expansion code")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8765")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--locale", default=REFERENCE_LOCALE, help="判断 repo 已有系列的语言目录")
    parser.add_argument("--print-only", action="store_true", help="只输出缺失 code（逗号分隔），供脚本消费")
    args = parser.parse_args(argv)

    game = discover_game_expansions(args.bridge_url)
    repo = discover_repo_expansions(args.repo_root, args.locale)
    missing = find_missing_expansions(game, repo)

    if args.print_only:
        print(",".join(missing))
        return 0

    print(f"游戏系列 ({len(game)}): {game}")
    print(f"repo 已有 ({len(repo)}): {repo}")
    if missing:
        print(f"缺失系列 ({len(missing)}): {missing}")
        print(f"\n缺失 code（逗号分隔）:\n{','.join(missing)}")
    else:
        print("\n✅ 无缺失系列，repo 与游戏同步")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
