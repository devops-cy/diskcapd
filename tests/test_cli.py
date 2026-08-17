"""Tests for diskcapd command exit contracts."""

import io
from datetime import timedelta
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from diskcapd import cli
from diskcapd.notify import NotificationResult
from diskcapd.config import FilesystemConfig
from diskcapd.discovery import Filesystem
from diskcapd.monitor import FilesystemStatus
from diskcapd.state import StateRecord


def status_with_usage(used_percent):
    config = FilesystemConfig(
        mountpoint="/mnt/data",
        uuid="test-uuid",
        source="/dev/sda1",
        fstype="ext4",
        threshold=65,
    )

    return FilesystemStatus(
        config=config,
        mounted=True,
        block_backed=True,
        current_source="/dev/sda1",
        current_uuid="test-uuid",
        current_fstype="ext4",
        total_bytes=1000,
        used_bytes=650,
        available_bytes=350,
        used_percent=used_percent,
        problem=None,
    )


class CheckExitCodeTests(unittest.TestCase):
    def run_quietly(self, statuses):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            with (
                patch.object(cli.ui, "ANIMATION", False),
                patch(
                    "diskcapd.cli.load_runtime_status",
                    return_value=statuses,
                ),
                patch(
                    "diskcapd.cli.read_notification_recipient",
                    return_value="admin@example.invalid",
                ),
                patch(
                    "diskcapd.cli.send_notification",
                    return_value=NotificationResult(
                        recipient="admin@example.invalid"
                    ),
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                return cli.run_check(
                    Path("test.conf"),
                    state_path,
                )

    def test_healthy_check_returns_zero(self):
        code = self.run_quietly(
            [status_with_usage(10.0)]
        )

        self.assertEqual(code, 0)

    def test_violation_returns_one(self):
        code = self.run_quietly(
            [status_with_usage(65.0)]
        )

        self.assertEqual(code, 1)

    def test_operational_failure_returns_two(self):
        code = self.run_quietly(None)

        self.assertEqual(code, 2)



class QuietCheckTests(unittest.TestCase):
    def run_check_capture(self, statuses, state_path):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.load_runtime_status",
                return_value=statuses,
            ),
            patch(
                "diskcapd.cli.read_notification_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.send_notification",
                return_value=NotificationResult(
                    recipient="admin@example.com"
                ),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.run_check(
                Path("test.conf"),
                state_path,
                quiet=True,
            )

        return code, stdout.getvalue(), stderr.getvalue()

    def test_quiet_healthy_check_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            code, stdout, stderr = self.run_check_capture(
                [status_with_usage(10.0)],
                state_path,
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_quiet_new_violation_reports_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            code, stdout, stderr = self.run_check_capture(
                [status_with_usage(65.0)],
                state_path,
            )

        self.assertEqual(code, 1)
        self.assertIn(
            "ALERT /mnt/data: threshold",
            stdout,
        )
        self.assertEqual(stderr, "")

    def test_quiet_repeated_violation_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            first_code, first_stdout, _ = self.run_check_capture(
                [status_with_usage(65.0)],
                state_path,
            )

            second_code, second_stdout, second_stderr = (
                self.run_check_capture(
                    [status_with_usage(65.0)],
                    state_path,
                )
            )

        self.assertEqual(first_code, 1)
        self.assertIn("ALERT", first_stdout)

        self.assertEqual(second_code, 1)
        self.assertEqual(second_stdout, "")
        self.assertEqual(second_stderr, "")

    def test_quiet_recovery_reports_once(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"

            self.run_check_capture(
                [status_with_usage(65.0)],
                state_path,
            )

            code, stdout, stderr = self.run_check_capture(
                [status_with_usage(10.0)],
                state_path,
            )

        self.assertEqual(code, 0)
        self.assertIn(
            "RECOVERY /mnt/data: threshold -> ok",
            stdout,
        )
        self.assertEqual(stderr, "")

    def test_parser_accepts_quiet_check(self):
        args = cli.build_parser().parse_args(
            ["check", "--quiet"]
        )

        self.assertTrue(args.quiet)



class AutomaticNotificationTests(unittest.TestCase):
    def test_alert_is_sent_before_state_is_committed(self):
        status = status_with_usage(65.0)

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.load_runtime_status",
                return_value=[status],
            ),
            patch(
                "diskcapd.cli.read_notification_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.read_state",
                return_value={},
            ),
            patch(
                "diskcapd.cli.send_notification",
                return_value=NotificationResult(
                    recipient="admin@example.com"
                ),
            ) as send,
            patch(
                "diskcapd.cli.write_state",
            ) as write,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            code = cli.run_check(
                Path("test.conf"),
                Path("state.json"),
                quiet=True,
            )

        self.assertEqual(code, 1)
        send.assert_called_once()
        write.assert_called_once()

    def test_notification_failure_does_not_commit_state(self):
        status = status_with_usage(65.0)

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.load_runtime_status",
                return_value=[status],
            ),
            patch(
                "diskcapd.cli.read_notification_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.read_state",
                return_value={},
            ),
            patch(
                "diskcapd.cli.send_notification",
                side_effect=cli.NotificationError(
                    "SMTP unavailable"
                ),
            ) as send,
            patch(
                "diskcapd.cli.write_state",
            ) as write,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            code = cli.run_check(
                Path("test.conf"),
                Path("state.json"),
                quiet=True,
            )

        self.assertEqual(code, 3)
        send.assert_called_once()
        write.assert_not_called()

    def test_repeated_violation_does_not_send_again(self):
        status = status_with_usage(65.0)

        now = cli.utc_now()

        previous = {
            "/mnt/data": StateRecord(
                uuid="test-uuid",
                condition="threshold",
                used_percent=65.0,
                last_notification_at=now,
            )
        }

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.load_runtime_status",
                return_value=[status],
            ),
            patch(
                "diskcapd.cli.read_notification_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.read_state",
                return_value=previous,
            ),
            patch(
                "diskcapd.cli.send_notification",
            ) as send,
            patch(
                "diskcapd.cli.write_state",
            ) as write,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            code = cli.run_check(
                Path("test.conf"),
                Path("state.json"),
                quiet=True,
            )

        self.assertEqual(code, 1)
        send.assert_not_called()
        write.assert_not_called()

    def test_due_reminder_is_sent_and_committed(self):
        status = status_with_usage(65.0)
        now = cli.utc_now()

        previous = {
            "/mnt/data": StateRecord(
                uuid="test-uuid",
                condition="threshold",
                used_percent=65.0,
                last_notification_at=now - timedelta(hours=24),
            )
        }

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.utc_now",
                return_value=now,
            ),
            patch(
                "diskcapd.cli.load_runtime_status",
                return_value=[status],
            ),
            patch(
                "diskcapd.cli.read_notification_recipient",
                return_value="admin@example.invalid",
            ),
            patch(
                "diskcapd.cli.read_state",
                return_value=previous,
            ),
            patch(
                "diskcapd.cli.send_notification",
                return_value=NotificationResult(
                    recipient="admin@example.invalid"
                ),
            ) as send,
            patch(
                "diskcapd.cli.write_state",
            ) as write,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            code = cli.run_check(
                Path("test.conf"),
                Path("state.json"),
                quiet=True,
            )

        self.assertEqual(code, 1)
        send.assert_called_once()
        write.assert_called_once()

        written_state = write.call_args.args[1]

        self.assertEqual(
            written_state["/mnt/data"].last_notification_at,
            now,
        )

    def test_failed_reminder_does_not_advance_state(self):
        status = status_with_usage(65.0)
        now = cli.utc_now()

        previous = {
            "/mnt/data": StateRecord(
                uuid="test-uuid",
                condition="threshold",
                used_percent=65.0,
                last_notification_at=now - timedelta(hours=24),
            )
        }

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.utc_now",
                return_value=now,
            ),
            patch(
                "diskcapd.cli.load_runtime_status",
                return_value=[status],
            ),
            patch(
                "diskcapd.cli.read_notification_recipient",
                return_value="admin@example.invalid",
            ),
            patch(
                "diskcapd.cli.read_state",
                return_value=previous,
            ),
            patch(
                "diskcapd.cli.send_notification",
                side_effect=cli.NotificationError(
                    "SMTP unavailable"
                ),
            ) as send,
            patch(
                "diskcapd.cli.write_state",
            ) as write,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            code = cli.run_check(
                Path("test.conf"),
                Path("state.json"),
                quiet=True,
            )

        self.assertEqual(code, 3)
        send.assert_called_once()
        write.assert_not_called()

    def test_recovery_is_sent_and_committed(self):
        status = status_with_usage(10.0)

        previous = {
            "/mnt/data": StateRecord(
                uuid="test-uuid",
                condition="threshold",
                used_percent=65.0,
            )
        }

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.load_runtime_status",
                return_value=[status],
            ),
            patch(
                "diskcapd.cli.read_notification_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.read_state",
                return_value=previous,
            ),
            patch(
                "diskcapd.cli.send_notification",
                return_value=NotificationResult(
                    recipient="admin@example.com"
                ),
            ) as send,
            patch(
                "diskcapd.cli.write_state",
            ) as write,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            code = cli.run_check(
                Path("test.conf"),
                Path("state.json"),
                quiet=True,
            )

        self.assertEqual(code, 0)
        send.assert_called_once()
        write.assert_called_once()



class NotificationCommandTests(unittest.TestCase):
    def test_existing_system_profile_sends_directly(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.system_profile_available",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.configure_system_profile",
            ) as configure,
            patch(
                "diskcapd.cli.send_notification",
                return_value=NotificationResult(
                    recipient="admin@example.com"
                ),
            ) as send,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.run_test_notification(
                "admin@example.com"
            )

        self.assertEqual(code, 0)
        configure.assert_not_called()
        send.assert_called_once()

    def test_missing_profile_declined_returns_three(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.system_profile_available",
                return_value=False,
            ),
            patch(
                "builtins.input",
                return_value="n",
            ),
            patch(
                "diskcapd.cli.send_notification",
            ) as send,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.run_test_notification(
                "admin@example.com"
            )

        self.assertEqual(code, 3)
        send.assert_not_called()

    def test_missing_profile_can_be_configured(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(cli.ui, "ANIMATION", False),
            patch(
                "diskcapd.cli.system_profile_available",
                side_effect=[False, True],
            ),
            patch(
                "builtins.input",
                return_value="y",
            ),
            patch(
                "diskcapd.cli.configure_system_profile",
            ) as configure,
            patch(
                "diskcapd.cli.send_notification",
                return_value=NotificationResult(
                    recipient="admin@example.com"
                ),
            ) as send,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.run_test_notification(
                "admin@example.com"
            )

        self.assertEqual(code, 0)
        configure.assert_called_once_with()
        send.assert_called_once()


class SetupNotificationTests(unittest.TestCase):
    def test_notification_setup_configures_missing_profile(self):
        with (
            patch(
                "diskcapd.cli.system_profile_available",
                side_effect=[False, True],
            ),
            patch(
                "diskcapd.cli.prompt_yes_no",
                side_effect=[True, True],
            ),
            patch(
                "diskcapd.cli.configure_system_profile",
            ) as configure,
            patch(
                "diskcapd.cli.send_notification",
                return_value=NotificationResult(
                    recipient="admin@example.com"
                ),
            ) as send,
            patch.object(cli.ui, "ANIMATION", False),
        ):
            result = cli.run_notification_setup(
                "admin@example.com"
            )

        self.assertTrue(result)
        configure.assert_called_once_with()
        send.assert_called_once()

    def test_notification_setup_failure_can_abort(self):
        with (
            patch(
                "diskcapd.cli.system_profile_available",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.send_notification",
                side_effect=cli.NotificationError(
                    "SMTP authentication failed"
                ),
            ),
            patch(
                "diskcapd.cli.prompt_yes_no",
                return_value=False,
            ),
            patch.object(cli.ui, "ANIMATION", False),
        ):
            result = cli.run_notification_setup(
                "admin@example.com"
            )

        self.assertFalse(result)

    def test_setup_writes_verified_notification_recipient(self):
        filesystem = Filesystem(
            source="/dev/sda1",
            device="/dev/sda1",
            target="/",
            fstype="ext4",
            uuid="test-uuid",
            total_bytes=1000,
            used_bytes=100,
            available_bytes=900,
            used_percent=10.0,
        )

        with (
            patch.object(
                cli.sys.stdin,
                "isatty",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.discover_filesystems",
                return_value=[filesystem],
            ),
            patch(
                "diskcapd.cli.prompt_yes_no",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.prompt_threshold",
                return_value=65,
            ),
            patch(
                "diskcapd.cli.prompt_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.run_notification_setup",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.write_configuration",
            ) as write,
            patch.object(cli.ui, "ANIMATION", False),
        ):
            code = cli.run_setup(
                Path("test-diskcapd.conf")
            )

        self.assertEqual(code, 0)

        write.assert_called_once()

        args, kwargs = write.call_args

        self.assertEqual(
            kwargs["notification_recipient"],
            "admin@example.com",
        )
        self.assertEqual(
            args[1][0].mountpoint,
            "/",
        )


class SetupUnattendedMonitoringTests(unittest.TestCase):
    def filesystem(self):
        return Filesystem(
            source="/dev/sda1",
            device="/dev/sda1",
            target="/",
            fstype="ext4",
            uuid="test-uuid",
            total_bytes=1000,
            used_bytes=100,
            available_bytes=900,
            used_percent=10.0,
        )

    def test_system_setup_can_enable_unattended_monitoring(self):
        with (
            patch.object(cli.sys.stdin, "isatty", return_value=True),
            patch(
                "diskcapd.cli.discover_filesystems",
                return_value=[self.filesystem()],
            ),
            patch(
                "diskcapd.cli.prompt_yes_no",
                side_effect=[True, True],
            ),
            patch(
                "diskcapd.cli.prompt_threshold",
                return_value=65,
            ),
            patch(
                "diskcapd.cli.prompt_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.run_notification_setup",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.write_configuration",
            ),
            patch(
                "diskcapd.cli.enable_unattended_monitoring",
                return_value=(True, ""),
            ) as enable,
            patch.object(cli.ui, "ANIMATION", False),
        ):
            code = cli.run_setup(cli.DEFAULT_CONFIG_PATH)

        self.assertEqual(code, 0)
        enable.assert_called_once_with()

    def test_system_setup_can_leave_unattended_monitoring_disabled(self):
        with (
            patch.object(cli.sys.stdin, "isatty", return_value=True),
            patch(
                "diskcapd.cli.discover_filesystems",
                return_value=[self.filesystem()],
            ),
            patch(
                "diskcapd.cli.prompt_yes_no",
                side_effect=[True, False],
            ),
            patch(
                "diskcapd.cli.prompt_threshold",
                return_value=65,
            ),
            patch(
                "diskcapd.cli.prompt_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.run_notification_setup",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.write_configuration",
            ),
            patch(
                "diskcapd.cli.enable_unattended_monitoring",
            ) as enable,
            patch.object(cli.ui, "ANIMATION", False),
        ):
            code = cli.run_setup(cli.DEFAULT_CONFIG_PATH)

        self.assertEqual(code, 0)
        enable.assert_not_called()

    def test_custom_configuration_does_not_offer_system_timer_activation(self):
        prompt = unittest.mock.Mock(return_value=True)

        with (
            patch.object(cli.sys.stdin, "isatty", return_value=True),
            patch(
                "diskcapd.cli.discover_filesystems",
                return_value=[self.filesystem()],
            ),
            patch(
                "diskcapd.cli.prompt_yes_no",
                prompt,
            ),
            patch(
                "diskcapd.cli.prompt_threshold",
                return_value=65,
            ),
            patch(
                "diskcapd.cli.prompt_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.run_notification_setup",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.write_configuration",
            ),
            patch(
                "diskcapd.cli.enable_unattended_monitoring",
            ) as enable,
            patch.object(cli.ui, "ANIMATION", False),
        ):
            code = cli.run_setup(Path("custom.conf"))

        self.assertEqual(code, 0)
        self.assertEqual(prompt.call_count, 1)
        enable.assert_not_called()

    def test_timer_activation_failure_keeps_written_configuration(self):
        with (
            patch.object(cli.sys.stdin, "isatty", return_value=True),
            patch(
                "diskcapd.cli.discover_filesystems",
                return_value=[self.filesystem()],
            ),
            patch(
                "diskcapd.cli.prompt_yes_no",
                side_effect=[True, True],
            ),
            patch(
                "diskcapd.cli.prompt_threshold",
                return_value=65,
            ),
            patch(
                "diskcapd.cli.prompt_recipient",
                return_value="admin@example.com",
            ),
            patch(
                "diskcapd.cli.run_notification_setup",
                return_value=True,
            ),
            patch(
                "diskcapd.cli.write_configuration",
            ) as write,
            patch(
                "diskcapd.cli.enable_unattended_monitoring",
                return_value=(False, "systemctl failed"),
            ),
            patch.object(cli.ui, "ANIMATION", False),
        ):
            code = cli.run_setup(cli.DEFAULT_CONFIG_PATH)

        self.assertEqual(code, 2)
        write.assert_called_once()

    def test_timer_activation_uses_packaged_systemd_unit(self):
        with patch("diskcapd.cli.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ""
            run.return_value.stderr = ""

            enabled, error = cli.enable_unattended_monitoring()

        self.assertTrue(enabled)
        self.assertEqual(error, "")
        run.assert_called_once_with(
            [
                "systemctl",
                "enable",
                "--now",
                "diskcapd.timer",
            ],
            check=False,
            capture_output=True,
            text=True,
        )


class ProductionPathTests(unittest.TestCase):
    def test_setup_uses_system_configuration_path_by_default(self):
        args = cli.build_parser().parse_args(["setup"])

        self.assertEqual(
            args.config,
            Path("/etc/diskcapd/diskcapd.conf"),
        )

    def test_status_uses_system_configuration_path_by_default(self):
        args = cli.build_parser().parse_args(["status"])

        self.assertEqual(
            args.config,
            Path("/etc/diskcapd/diskcapd.conf"),
        )

    def test_check_uses_system_runtime_paths_by_default(self):
        args = cli.build_parser().parse_args(["check"])

        self.assertEqual(
            args.config,
            Path("/etc/diskcapd/diskcapd.conf"),
        )
        self.assertEqual(
            args.state,
            Path("/var/lib/diskcapd/state.json"),
        )

    def test_development_paths_can_be_overridden(self):
        args = cli.build_parser().parse_args(
            [
                "check",
                "--config",
                "./diskcapd.conf",
                "--state",
                "./diskcapd-state.json",
            ]
        )

        self.assertEqual(
            args.config,
            Path("diskcapd.conf"),
        )
        self.assertEqual(
            args.state,
            Path("diskcapd-state.json"),
        )


if __name__ == "__main__":
    unittest.main()
