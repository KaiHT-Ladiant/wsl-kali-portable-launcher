#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for portable WSL helper logic (no Windows required)."""

from __future__ import annotations

import unittest

from kali_launcher import (
    decode_subprocess_output,
    normalize_wsl_base_path,
    format_wsl_base_path,
    parse_lxss_registry_output,
)


class DecodeTests(unittest.TestCase):
    def test_utf16_le_ascii(self) -> None:
        raw = "OK\r\n".encode("utf-16-le")
        self.assertEqual(decode_subprocess_output(raw), "OK")

    def test_utf16_le_korean_path_error(self) -> None:
        msg = "지정된 경로를 찾을 수 없습니다."
        raw = msg.encode("utf-16-le")
        self.assertEqual(decode_subprocess_output(raw), msg)

    def test_cp949_korean(self) -> None:
        msg = "파일을 찾을 수 없습니다."
        raw = msg.encode("cp949")
        self.assertEqual(decode_subprocess_output(raw), msg)

    def test_utf8(self) -> None:
        self.assertEqual(decode_subprocess_output("hello".encode("utf-8")), "hello")


class PathTests(unittest.TestCase):
    def test_normalize_strips_prefix(self) -> None:
        self.assertEqual(
            normalize_wsl_base_path(r"\\?\F:\0.Kali\kali-portable"),
            normalize_wsl_base_path(r"F:\0.Kali\kali-portable"),
        )

    def test_format_adds_prefix(self) -> None:
        self.assertTrue(format_wsl_base_path(r"F:\0.Kali\kali-portable").startswith("\\\\?\\"))

    def test_windows_to_wsl_mnt(self) -> None:
        from kali_launcher import windows_path_to_wsl_mnt

        converted = windows_path_to_wsl_mnt(r"C:\Users\kaiht\AppData\Local\KaliLauncher\winkex-cache\passwd")
        self.assertTrue(converted.startswith("/mnt/c/"))
        self.assertIn("KaliLauncher/winkex-cache/passwd", converted.replace("\\", "/"))


class RegistryParseTests(unittest.TestCase):
    def test_parse_lxss_output(self) -> None:
        sample = """
HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss
    DefaultDistribution    REG_SZ    {11111111-1111-1111-1111-111111111111}

HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss\\{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}
    State    REG_DWORD    0x1
    DistributionName    REG_SZ    kali-linux
    BasePath    REG_SZ    \\\\?\\E:\\0.Kali\\kali-portable
    Version    REG_DWORD    0x2
"""
        entries = parse_lxss_registry_output(sample)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "kali-linux")
        self.assertIn("E:\\0.Kali\\kali-portable", entries[0]["base_path"])
        self.assertTrue(entries[0]["guid_key"].endswith("{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}"))


class HcsDetectionTests(unittest.TestCase):
    def test_hcs_timeout_korean(self) -> None:
        from kali_launcher import KaliLauncher

        launcher = KaliLauncher.__new__(KaliLauncher)
        detail = (
            "가상 머신 또는 컨테이너에서 응답을 받지 못했기 때문에 작업 시간이 초과되었습니다.\n"
            "오류 코드: Wsl/Service/HCS_E_CONNECTION_TIMEOUT"
        )
        self.assertTrue(launcher._is_hcs_timeout(detail))
        self.assertTrue(launcher._wsl_output_unhealthy(detail))


if __name__ == "__main__":
    unittest.main()
