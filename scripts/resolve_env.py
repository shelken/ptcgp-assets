#!/usr/bin/env python3
"""探测 frida-test 目录与 bridge port，供 justfile 和更新脚本消费。

不硬编码路径：按搜索链找到第一个通过校验的 frida-test 目录；
bridge port 探测复用/拉起判断由 resolve_bridge 决定，实际拉起仍由
update_pack_images.py 的 --bridge-command 机制完成。
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 搜索链：环境变量优先，依次兜底常见位置（"active" 暗示会移动，不能写死单一路径）
SEARCH_PATHS = [
    Path("~/Code/active/frida-test").expanduser(),
    Path("~/Code/frida-test").expanduser(),
    REPO_ROOT.parent / "frida-test",
]

# bridge 默认端口
DEFAULT_BRIDGE_PORT = 8765

# bridge 探测超时（秒）
BRIDGE_PROBE_TIMEOUT = 2


def _is_valid_frida_test_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "package.json").is_file()
        and (path / "src" / "cli" / "index.ts").is_file()
    )


def resolve_frida_test_dir() -> Path:
    """返回校验通过的 frida-test 目录，全部失败抛 SystemExit。"""
    env_dir = os.environ.get("FRIDA_TEST_DIR")
    if env_dir:
        candidate = Path(env_dir).expanduser()
        if _is_valid_frida_test_dir(candidate):
            return candidate
        sys.exit(
            f"❌ FRIDA_TEST_DIR={env_dir} 不是合法的 frida-test 目录"
            f"（需含 package.json 和 src/cli/index.ts）"
        )

    for path in SEARCH_PATHS:
        if _is_valid_frida_test_dir(path):
            return path

    sys.exit(
        "❌ 未找到 frida-test 目录，请设置环境变量 FRIDA_TEST_DIR 指向 frida-test 仓库"
    )


def bridge_port_open(port: int = DEFAULT_BRIDGE_PORT) -> bool:
    """检测 port 是否在监听（只判 TCP 连通，不判是不是 bridge）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(BRIDGE_PROBE_TIMEOUT)
        return sock.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="探测更新流程所需环境")
    parser.add_argument("--frida-test-dir", action="store_true", help="输出 frida-test 目录路径")
    parser.add_argument("--bridge-url", action="store_true", help="输出 bridge url")
    parser.add_argument("--bridge-port", type=int, default=DEFAULT_BRIDGE_PORT)
    args = parser.parse_args()

    if args.frida_test_dir:
        print(resolve_frida_test_dir())
    elif args.bridge_url:
        # bridge 是否在跑由 update_pack_images.py 的 wait_for_bridge 判断；
        # 这里只输出默认 url，未在跑时由其 --bridge-command 拉起
        print(f"http://127.0.0.1:{args.bridge_port}")
