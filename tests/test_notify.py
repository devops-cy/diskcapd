"""Tests for diskcapd Postout notification delivery."""

import subprocess
import unittest
from unittest.mock import patch

from diskcapd.notify import (
    NotificationError,
    configure_system_profile,
    send_notification,
    system_profile_available,
)


class NotificationTests(unittest.TestCase):
    def test_successful_postout_delivery(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            result = send_notification(
                recipient="admin@example.com",
                subject="diskcapd test",
                body="Test body",
            )

        self.assertEqual(
            result.recipient,
            "admin@example.com",
        )

        run.assert_called_once_with(
            [
                "/usr/bin/postout",
                "--profiles-file",
                "/etc/postout/profiles.json",
                "--profile",
                "diskcapd",
                "--to",
                "admin@example.com",
                "--subject",
                "diskcapd test",
                "--body",
                "Test body",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_html_delivery_uses_postout_stdin(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            result = send_notification(
                recipient="admin@example.invalid",
                subject="[diskcapd] ALERT server01: /",
                body="Plain fallback",
                html_body="<html><body>Alert</body></html>",
            )

        self.assertEqual(
            result.recipient,
            "admin@example.invalid",
        )

        run.assert_called_once_with(
            [
                "/usr/bin/postout",
                "--profiles-file",
                "/etc/postout/profiles.json",
                "--profile",
                "diskcapd",
                "--to",
                "admin@example.invalid",
                "--subject",
                "[diskcapd] ALERT server01: /",
                "--html",
                "--body-file",
                "-",
                "--text-fallback",
                "Plain fallback",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            input="<html><body>Alert</body></html>",
        )

    def test_empty_recipient_is_error(self):
        with patch(
            "diskcapd.notify.postout_path",
            return_value="/usr/bin/postout",
        ):
            with self.assertRaisesRegex(
                NotificationError,
                "recipient is required",
            ):
                send_notification(
                    recipient="",
                    subject="test",
                    body="test",
                )

    def test_missing_postout_is_error(self):
        with patch(
            "diskcapd.notify.postout_path",
            return_value=None,
        ):
            with self.assertRaisesRegex(
                NotificationError,
                "postout executable was not found",
            ):
                send_notification(
                    recipient="admin@example.com",
                    subject="test",
                    body="test",
                )

    def test_postout_failure_is_error(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="[ERROR] SMTP connection failed",
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ),
        ):
            with self.assertRaisesRegex(
                NotificationError,
                "SMTP connection failed",
            ):
                send_notification(
                    recipient="admin@example.com",
                    subject="test",
                    body="test",
                )

    def test_system_profile_is_detected(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "Available Postout profiles\n"
                "\n"
                "Profiles file: /etc/postout/profiles.json\n"
                "\n"
                "NAME\n"
                "diskcapd\n"
            ),
            stderr="",
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ),
        ):
            self.assertTrue(system_profile_available())

    def test_missing_system_profile_is_detected(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "Available Postout profiles\n"
                "\n"
                "Profiles file: /etc/postout/profiles.json\n"
                "\n"
                "NAME\n"
                "other-profile\n"
            ),
            stderr="",
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ),
        ):
            self.assertFalse(system_profile_available())

    def test_profile_inspection_failure_is_error(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr="Unable to read profiles",
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ),
        ):
            with self.assertRaisesRegex(
                NotificationError,
                "Unable to read profiles",
            ):
                system_profile_available()

    def test_configuration_uses_sudo_for_normal_user(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.os.geteuid",
                return_value=1000,
            ),
            patch(
                "diskcapd.notify.shutil.which",
                return_value="/usr/bin/sudo",
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            configure_system_profile()

        run.assert_called_once_with(
            [
                "/usr/bin/sudo",
                "/usr/bin/postout",
                "config",
                "--system",
                "--profile",
                "diskcapd",
                "--display-name",
                "[diskcapd]",
            ],
            check=False,
        )


    def test_configuration_runs_postout_directly_as_root(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
        )

        with (
            patch(
                "diskcapd.notify.postout_path",
                return_value="/usr/bin/postout",
            ),
            patch(
                "diskcapd.notify.os.geteuid",
                return_value=0,
            ),
            patch(
                "diskcapd.notify.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            configure_system_profile()

        run.assert_called_once_with(
            [
                "/usr/bin/postout",
                "config",
                "--system",
                "--profile",
                "diskcapd",
                "--display-name",
                "[diskcapd]",
            ],
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
