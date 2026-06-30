import time
import unittest
from unittest.mock import MagicMock, patch

from scripts.bridge_client import _wait_for_bridge


class WaitForBridgeTest(unittest.TestCase):
    def test_returns_immediately_when_port_is_connectable(self) -> None:
        # 端口可连 → 立即返回，不等满超时
        process = MagicMock()
        process.poll.return_value = None
        start = time.monotonic()

        with patch("scripts.bridge_client._check_port_open", return_value=True):
            _wait_for_bridge("http://127.0.0.1:8765", process)

        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2.0, "should return immediately once port is open")

    def test_raises_when_bridge_process_exits_early(self) -> None:
        # bridge 进程已退出 → 立即报错，不空等
        process = MagicMock()
        process.poll.return_value = 1
        process.returncode = 1

        with self.assertRaisesRegex(RuntimeError, "exited early"):
            _wait_for_bridge("http://127.0.0.1:8765", process)

    def test_times_out_when_port_never_opens(self) -> None:
        # 端口始终拒绝 → 超时报错，不刷屏调用业务接口
        process = MagicMock()
        process.poll.return_value = None

        with (
            patch("scripts.bridge_client._check_port_open", return_value=False),
            patch("scripts.bridge_client.BRIDGE_START_TIMEOUT_SECONDS", 0.5),
        ):
            with self.assertRaisesRegex(TimeoutError, "did not respond in time"):
                _wait_for_bridge("http://127.0.0.1:8765", process)


if __name__ == "__main__":
    unittest.main()
