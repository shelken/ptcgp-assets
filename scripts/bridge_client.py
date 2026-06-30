"""bridge 客户端：封装 frida-test bridge 的启动、等待、请求、关闭生命周期。

复用模式：先尝试请求已在跑的 bridge，失败则拉起新 bridge 再请求，用完关闭。
update_pack_images.py 和 list_missing_expansions.py 共享这套流程，避免重复。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.resolve_env import (
    DEFAULT_BRIDGE_PORT,
    resolve_bridge_command,
    resolve_bridge_cwd,
    resolve_frida_test_dir,
)

BRIDGE_START_TIMEOUT_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 180


def _check_port_open(bridge_url: str, timeout: float = 2.0) -> bool:
    # 只检测 TCP 端口连通，不调用业务接口——避免探活触发 frida attach 副作用，
    # 也避免把 bridge 已启动但 frida 故障的 500 错误误判为“还没启动”而无限重试。
    parsed = urllib.parse.urlparse(bridge_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def request_bridge(bridge_url: str, method: str, params: dict | None = None) -> bytes:
    """向 bridge 发 POST 请求，返回响应原始 bytes。"""
    payload = json.dumps({"method": method, "params": params or {}}).encode("utf-8")
    request = urllib.request.Request(
        f"{bridge_url.rstrip('/')}/ptcgp/run",
        data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )
    print(f"[bridge-client] requesting method={method} params={params or {}}", file=sys.stderr)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"bridge request failed status={error.code}: {body}") from error


def _wait_for_bridge(bridge_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + BRIDGE_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"bridge process exited early with code {process.returncode}")
        if _check_port_open(bridge_url):
            return
        time.sleep(1)
    raise TimeoutError("bridge did not respond in time")


class BridgeSession:
    """bridge 生命周期管理：复用已在跑的 bridge，否则拉起；用完关闭自启的。

    用法：
        with BridgeSession(bridge_url) as session:
            resp = session.request("ptcgp.packImages.raw", {...})
    """

    def __init__(
        self,
        bridge_url: str = f"http://127.0.0.1:{DEFAULT_BRIDGE_PORT}",
        *,
        bridge_command: str | None = None,
        bridge_cwd: Path | None = None,
    ) -> None:
        self.bridge_url = bridge_url
        # 缺省自动探测 bridge command/cwd
        if bridge_command is None:
            frida_dir = resolve_frida_test_dir()
            # 从 bridge_url 解析 port，保证拉起的 bridge 和请求的 url 端口一致
            port = urllib.parse.urlparse(bridge_url).port or DEFAULT_BRIDGE_PORT
            bridge_command = resolve_bridge_command(frida_dir, port=port)
            if bridge_cwd is None:
                bridge_cwd = resolve_bridge_cwd(frida_dir)
        self.bridge_command = bridge_command
        self.bridge_cwd = bridge_cwd
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> "BridgeSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(self, method: str, params: dict | None = None) -> bytes:
        """请求 bridge；若 bridge 未在跑则拉起后重试。"""
        try:
            return request_bridge(self.bridge_url, method, params)
        except (ConnectionError, OSError):
            # bridge 未在跑，拉起
            if self.bridge_command is None:
                raise
            print(f"[bridge-client] starting bridge command={self.bridge_command}", file=sys.stderr)
            self._process = subprocess.Popen(self.bridge_command.split(), cwd=self.bridge_cwd)
            _wait_for_bridge(self.bridge_url, self._process)
            return request_bridge(self.bridge_url, method, params)

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
