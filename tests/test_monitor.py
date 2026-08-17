"""Tests for diskcapd filesystem monitoring."""

import unittest
from unittest.mock import patch

from diskcapd.config import FilesystemConfig
from diskcapd.monitor import evaluate_filesystem


def filesystem_config(threshold=65):
    return FilesystemConfig(
        mountpoint="/mnt/data",
        uuid="expected-uuid",
        source="/dev/sda1",
        fstype="ext4",
        threshold=threshold,
    )


class MonitoringTests(unittest.TestCase):
    def test_missing_mount_is_violation(self):
        config = filesystem_config()

        with patch(
            "diskcapd.monitor._find_exact_mount",
            return_value=None,
        ):
            status = evaluate_filesystem(config)

        self.assertTrue(status.violation)
        self.assertFalse(status.mounted)
        self.assertIn(
            "not mounted",
            status.problem or "",
        )

    def test_changed_source_with_same_uuid_is_healthy(self):
        config = filesystem_config()

        with (
            patch(
                "diskcapd.monitor._find_exact_mount",
                return_value=(
                    "/dev/sdb1",
                    "ext4",
                    "expected-uuid",
                ),
            ),
            patch(
                "diskcapd.monitor.device_path",
                return_value="/dev/sdb1",
            ),
            patch(
                "diskcapd.monitor.read_usage",
                return_value=(1000, 100, 900, 10.0),
            ),
        ):
            status = evaluate_filesystem(config)

        self.assertFalse(status.violation)
        self.assertEqual(status.current_source, "/dev/sdb1")
        self.assertEqual(status.current_uuid, "expected-uuid")

    def test_wrong_uuid_is_violation(self):
        config = filesystem_config()

        with (
            patch(
                "diskcapd.monitor._find_exact_mount",
                return_value=(
                    "/dev/sda1",
                    "ext4",
                    "different-uuid",
                ),
            ),
            patch(
                "diskcapd.monitor.device_path",
                return_value="/dev/sda1",
            ),
        ):
            status = evaluate_filesystem(config)

        self.assertTrue(status.violation)
        self.assertIn(
            "unexpected filesystem mounted",
            status.problem or "",
        )

    def test_non_block_backed_mount_is_violation(self):
        config = filesystem_config()

        with (
            patch(
                "diskcapd.monitor._find_exact_mount",
                return_value=(
                    "server:/shared",
                    "nfs4",
                    "expected-uuid",
                ),
            ),
            patch(
                "diskcapd.monitor.device_path",
                return_value=None,
            ),
        ):
            status = evaluate_filesystem(config)

        self.assertTrue(status.violation)
        self.assertFalse(status.block_backed)

    def test_usage_below_threshold_is_healthy(self):
        config = filesystem_config(threshold=65)

        with (
            patch(
                "diskcapd.monitor._find_exact_mount",
                return_value=(
                    "/dev/sda1",
                    "ext4",
                    "expected-uuid",
                ),
            ),
            patch(
                "diskcapd.monitor.device_path",
                return_value="/dev/sda1",
            ),
            patch(
                "diskcapd.monitor.read_usage",
                return_value=(1000, 649, 351, 64.9),
            ),
        ):
            status = evaluate_filesystem(config)

        self.assertFalse(status.violation)
        self.assertFalse(status.threshold_exceeded)

    def test_threshold_is_inclusive(self):
        config = filesystem_config(threshold=65)

        with (
            patch(
                "diskcapd.monitor._find_exact_mount",
                return_value=(
                    "/dev/sda1",
                    "ext4",
                    "expected-uuid",
                ),
            ),
            patch(
                "diskcapd.monitor.device_path",
                return_value="/dev/sda1",
            ),
            patch(
                "diskcapd.monitor.read_usage",
                return_value=(1000, 650, 350, 65.0),
            ),
        ):
            status = evaluate_filesystem(config)

        self.assertTrue(status.threshold_exceeded)
        self.assertTrue(status.violation)


if __name__ == "__main__":
    unittest.main()
