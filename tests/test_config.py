"""Tests for diskcapd configuration handling."""

import configparser
import tempfile
import unittest
from pathlib import Path

from diskcapd.config import (
    ConfigurationError,
    FilesystemConfig,
    read_configuration,
    read_notification_recipient,
    write_configuration,
)


class ConfigurationTests(unittest.TestCase):
    def test_configuration_round_trip(self):
        filesystem = FilesystemConfig(
            mountpoint="/mnt/data",
            uuid="11111111-2222-3333-4444-555555555555",
            source="/dev/sdb1",
            fstype="ext4",
            threshold=65,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"

            write_configuration(path, [filesystem])
            loaded = read_configuration(path)

        self.assertEqual(loaded, [filesystem])

    def test_missing_uuid_is_rejected(self):
        content = """[general]
format_version = 2

[filesystem:/]
mountpoint = /
source = /dev/sda1
filesystem = ext4
threshold = 65
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"
            path.write_text(content)

            with self.assertRaisesRegex(
                ConfigurationError,
                "filesystem UUID is missing",
            ):
                read_configuration(path)

    def test_invalid_threshold_is_rejected(self):
        content = """[general]
format_version = 2

[filesystem:/]
mountpoint = /
uuid = test-uuid
source = /dev/sda1
filesystem = ext4
threshold = 100
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"
            path.write_text(content)

            with self.assertRaisesRegex(
                ConfigurationError,
                "threshold must be between 1 and 99",
            ):
                read_configuration(path)

    def test_old_configuration_format_is_rejected(self):
        content = """[general]
format_version = 1

[filesystem:/]
mountpoint = /
uuid = test-uuid
source = /dev/sda1
filesystem = ext4
threshold = 65
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"
            path.write_text(content)

            with self.assertRaisesRegex(
                ConfigurationError,
                "Unsupported configuration format",
            ):
                read_configuration(path)


    def test_notification_recipient_is_written(self):
        filesystem = FilesystemConfig(
            mountpoint="/mnt/data",
            uuid="test-uuid",
            source="/dev/sdb1",
            fstype="ext4",
            threshold=65,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"

            write_configuration(
                path,
                [filesystem],
                notification_recipient="admin@example.com",
            )

            parser = configparser.ConfigParser(
                interpolation=None
            )
            parser.read(path)

            loaded = read_configuration(path)

        self.assertEqual(loaded, [filesystem])
        self.assertEqual(
            parser["notifications"]["recipient"],
            "admin@example.com",
        )


    def test_notification_recipient_round_trip(self):
        filesystem = FilesystemConfig(
            mountpoint="/mnt/data",
            uuid="test-uuid",
            source="/dev/sdb1",
            fstype="ext4",
            threshold=65,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"

            write_configuration(
                path,
                [filesystem],
                notification_recipient="admin@example.com",
            )

            recipient = read_notification_recipient(path)

        self.assertEqual(
            recipient,
            "admin@example.com",
        )

    def test_missing_notification_section_is_rejected(self):
        content = """[general]
format_version = 2

[filesystem:/]
mountpoint = /
uuid = test-uuid
source = /dev/sda1
filesystem = ext4
threshold = 65
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"
            path.write_text(content)

            with self.assertRaisesRegex(
                ConfigurationError,
                r"missing the \[notifications\] section",
            ):
                read_notification_recipient(path)

    def test_empty_notification_recipient_is_rejected(self):
        content = """[general]
format_version = 2

[notifications]
recipient =

[filesystem:/]
mountpoint = /
uuid = test-uuid
source = /dev/sda1
filesystem = ext4
threshold = 65
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diskcapd.conf"
            path.write_text(content)

            with self.assertRaisesRegex(
                ConfigurationError,
                "Notification recipient is missing",
            ):
                read_notification_recipient(path)


if __name__ == "__main__":
    unittest.main()
