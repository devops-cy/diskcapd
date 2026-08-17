"""Tests for local filesystem discovery."""

import json
import stat
import subprocess
import unittest
from unittest.mock import patch

from diskcapd.discovery import device_path, discover_filesystems


class DevicePathTests(unittest.TestCase):
    def test_real_block_device_is_accepted(self):
        fake_stat = type(
            "FakeStat",
            (),
            {"st_mode": stat.S_IFBLK | 0o600},
        )()

        with patch("diskcapd.discovery.os.stat", return_value=fake_stat):
            self.assertEqual(
                device_path("/dev/sda1"),
                "/dev/sda1",
            )

    def test_non_dev_source_is_rejected(self):
        self.assertIsNone(
            device_path("server:/shared/data")
        )

    def test_non_block_dev_path_is_rejected(self):
        fake_stat = type(
            "FakeStat",
            (),
            {"st_mode": stat.S_IFREG | 0o600},
        )()

        with patch("diskcapd.discovery.os.stat", return_value=fake_stat):
            self.assertIsNone(
                device_path("/dev/not-a-block-device")
            )


class DiscoveryTests(unittest.TestCase):
    def test_discovery_excludes_network_and_read_only_mounts(self):
        payload = {
            "filesystems": [
                {
                    "source": "/dev/sda1",
                    "target": "/",
                    "fstype": "ext4",
                    "options": "rw,relatime",
                    "uuid": "root-uuid",
                },
                {
                    "source": "server:/shared",
                    "target": "/mnt/shared",
                    "fstype": "nfs4",
                    "options": "rw,relatime",
                    "uuid": None,
                },
                {
                    "source": "/dev/loop0",
                    "target": "/snap/example",
                    "fstype": "squashfs",
                    "options": "ro,relatime",
                    "uuid": "loop-uuid",
                },
            ]
        }

        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

        def fake_device_path(source):
            if source == "/dev/sda1":
                return source

            return None

        with (
            patch(
                "diskcapd.discovery.shutil.which",
                return_value="/usr/bin/findmnt",
            ),
            patch(
                "diskcapd.discovery.subprocess.run",
                return_value=completed,
            ),
            patch(
                "diskcapd.discovery.device_path",
                side_effect=fake_device_path,
            ),
            patch(
                "diskcapd.discovery.read_usage",
                return_value=(1000, 100, 900, 10.0),
            ),
        ):
            filesystems = discover_filesystems()

        self.assertEqual(len(filesystems), 1)
        self.assertEqual(filesystems[0].target, "/")
        self.assertEqual(filesystems[0].uuid, "root-uuid")


if __name__ == "__main__":
    unittest.main()
