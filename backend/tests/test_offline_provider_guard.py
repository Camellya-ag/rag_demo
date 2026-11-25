from __future__ import annotations

import unittest

import httpx

from backend.tests.offline_provider_guard import install_offline_llm_guard


class OfflineProviderGuardTests(unittest.TestCase):
    def test_guard_blocks_provider_http(self) -> None:
        install_offline_llm_guard()
        with httpx.Client() as client:
            with self.assertRaisesRegex(RuntimeError, "offline guard blocks external HTTP request"):
                client.get("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
