"""resolve_env 探测逻辑测试

保证 frida-test 目录探测的搜索链行为正确。
不依赖真实文件系统（用 unittest.mock.patch + tempfile 隔离）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.resolve_env as resolve_env


def _make_fake_frida_test(root: Path) -> Path:
    """构造一个通过校验的 frida-test 目录结构。"""
    (root / "src" / "cli").mkdir(parents=True)
    (root / "package.json").write_text("{}")
    (root / "src" / "cli" / "index.ts").write_text("")
    return root


class ResolveFridaTestDirTest(unittest.TestCase):
    def test_prefers_env_var(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fake = _make_fake_frida_test(tmp / "fake-frida-test")
            with mock.patch.dict("os.environ", {"FRIDA_TEST_DIR": str(fake)}), \
                 mock.patch.object(resolve_env, "SEARCH_PATHS", []):
                result = resolve_env.resolve_frida_test_dir()
            self.assertEqual(result, fake)

    def test_rejects_invalid_env_var(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fake = tmp / "invalid"
            fake.mkdir()
            (fake / "src" / "cli").mkdir(parents=True)
            (fake / "src" / "cli" / "index.ts").write_text("")
            with mock.patch.dict("os.environ", {"FRIDA_TEST_DIR": str(fake)}, clear=False), \
                 mock.patch.object(resolve_env, "SEARCH_PATHS", []):
                with self.assertRaises(SystemExit):
                    resolve_env.resolve_frida_test_dir()

    def test_falls_back_to_search_paths(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fake = _make_fake_frida_test(tmp / "search-hit")
            env = {k: v for k, v in __import__("os").environ.items() if k != "FRIDA_TEST_DIR"}
            with mock.patch.dict("os.environ", env, clear=True), \
                 mock.patch.object(resolve_env, "SEARCH_PATHS", [fake]):
                result = resolve_env.resolve_frida_test_dir()
            self.assertEqual(result, fake)

    def test_exits_when_all_fail(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = {k: v for k, v in __import__("os").environ.items() if k != "FRIDA_TEST_DIR"}
            with mock.patch.dict("os.environ", env, clear=True), \
                 mock.patch.object(resolve_env, "SEARCH_PATHS", [tmp / "nonexistent"]):
                with self.assertRaises(SystemExit):
                    resolve_env.resolve_frida_test_dir()


class ResolveBridgeCommandTest(unittest.TestCase):
    def test_resolve_bridge_command_and_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            fake = _make_fake_frida_test(Path(td) / "fake-frida-test")
            cmd = resolve_env.resolve_bridge_command(fake)
            self.assertIn("tsx", cmd)
            self.assertIn("bridge", cmd)
            self.assertIn(str(fake), cmd)

            cwd = resolve_env.resolve_bridge_cwd(fake)
            self.assertEqual(cwd, fake)


if __name__ == "__main__":
    unittest.main()
