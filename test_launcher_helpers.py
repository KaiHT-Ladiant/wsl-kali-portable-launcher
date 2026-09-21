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

    def test_format_plain_drive_path(self) -> None:
        from kali_launcher import format_wsl_base_path

        self.assertEqual(
            format_wsl_base_path(r"F:\0.Kali\kali-portable"),
            r"F:\0.Kali\kali-portable",
        )
        self.assertEqual(
            format_wsl_base_path(r"\\?\H:\0.Kali\kali-portable"),
            r"H:\0.Kali\kali-portable",
        )

    def test_windows_to_wsl_mnt(self) -> None:
        from kali_launcher import windows_path_to_wsl_mnt

        converted = windows_path_to_wsl_mnt(r"C:\Users\kaiht\AppData\Local\KaliLauncher\winkex-cache\passwd")
        self.assertEqual(
            converted,
            "/mnt/c/Users/kaiht/AppData/Local/KaliLauncher/winkex-cache/passwd",
        )
        self.assertEqual(
            windows_path_to_wsl_mnt(r"\\?\D:\cache\win-kex-win-x64.exe"),
            "/mnt/d/cache/win-kex-win-x64.exe",
        )


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


class VhdxCorruptMountTests(unittest.TestCase):
    def test_detects_0x80070570_korean(self) -> None:
        from kali_launcher import KaliLauncher

        launcher = KaliLauncher.__new__(KaliLauncher)
        detail = (
            "디스크 'H:\\0.Kali\\kali-portable\\ext4.vhdx'을(를) WSL2에 연결하지 못함: "
            "파일 또는 디렉터리가 손상되었기 때문에 읽을 수 없습니다.\n"
            "오류 코드: Wsl/Service/CreateInstance/MountDisk/HCS/0x80070570"
        )
        self.assertTrue(launcher._is_vhdx_corrupt_mount(detail))
        self.assertTrue(launcher._wsl_output_unhealthy(detail))

    def test_ignores_unrelated_mount_noise(self) -> None:
        from kali_launcher import KaliLauncher

        launcher = KaliLauncher.__new__(KaliLauncher)
        self.assertFalse(launcher._is_vhdx_corrupt_mount("MountDisk still starting"))
        self.assertFalse(launcher._is_hcs_timeout("MountDisk still starting"))

    def test_drive_hint_uses_current_path(self) -> None:
        from kali_launcher import KaliLauncher

        launcher = KaliLauncher.__new__(KaliLauncher)
        launcher.paths = {"wsl_install_dir": r"H:\0.Kali\kali-portable"}
        self.assertEqual(launcher._current_ssd_drive_hint(), "H:")


class DriveRemapTests(unittest.TestCase):
    def test_windows_drive_letter(self) -> None:
        from kali_launcher import windows_drive_letter

        self.assertEqual(windows_drive_letter(r"H:\0.Kali\kali-portable"), "H:")
        self.assertEqual(windows_drive_letter(r"\\?\F:\0.Kali\kali-portable"), "F:")
        self.assertEqual(windows_drive_letter(r"e:/tmp"), "E:")

    def test_remap_drive(self) -> None:
        from kali_launcher import remap_windows_path_drive

        self.assertEqual(
            remap_windows_path_drive(r"F:\0.Kali\kali-portable", "H:"),
            r"H:\0.Kali\kali-portable",
        )
        self.assertEqual(
            remap_windows_path_drive(r"\\?\F:\0.Kali\kali-portable", "H:"),
            r"\\?\H:\0.Kali\kali-portable",
        )

    def test_config_path_remaps_stale_drive(self) -> None:
        from unittest.mock import patch

        from kali_launcher import apply_config_to_paths

        paths = {
            "app_dir": r"H:\0.Kali",
            "base_dir": r"H:\0.Kali",
            "wsl_install_dir": r"H:\0.Kali\kali-portable",
            "tar_path": r"H:\0.Kali\kali-final.tar",
        }

        def fake_vhdx(install_dir: str):
            if install_dir.upper().startswith("H:"):
                return install_dir.rstrip("\\") + r"\ext4.vhdx"
            return None

        with (
            patch("kali_launcher.find_vhdx", side_effect=fake_vhdx),
            patch("kali_launcher.os.path.isdir", return_value=True),
            patch("kali_launcher.os.path.isfile", return_value=True),
        ):
            apply_config_to_paths(
                paths,
                {
                    "wsl_install_dir": r"F:\0.Kali\kali-portable",
                    "tar_path": r"F:\0.Kali\kali-final.tar",
                },
            )
        self.assertEqual(paths["wsl_install_dir"], r"H:\0.Kali\kali-portable")
        self.assertEqual(paths["tar_path"], r"H:\0.Kali\kali-final.tar")


if __name__ == "__main__":
    unittest.main()
