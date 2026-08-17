"""Tests for diskcapd notification report rendering."""

import unittest
from unittest.mock import patch

from diskcapd.config import FilesystemConfig
from diskcapd.monitor import FilesystemStatus
from diskcapd.report import (
    build_transition_notification,
    short_hostname,
)
from diskcapd.state import StateTransition


def make_status(
    mountpoint="/",
    source="/dev/sda1",
    fstype="ext4",
    used_percent=70.0,
    threshold=65,
):
    config = FilesystemConfig(
        mountpoint=mountpoint,
        uuid="test-uuid",
        source=source,
        fstype=fstype,
        threshold=threshold,
    )

    return FilesystemStatus(
        config=config,
        mounted=True,
        block_backed=True,
        current_source=source,
        current_uuid="test-uuid",
        current_fstype=fstype,
        total_bytes=100 * 1024**3,
        used_bytes=70 * 1024**3,
        available_bytes=30 * 1024**3,
        used_percent=used_percent,
        problem=None,
    )


def make_transition(
    event="alert",
    mountpoint="/",
):
    return StateTransition(
        mountpoint=mountpoint,
        uuid="test-uuid",
        previous_condition=(
            "threshold"
            if event == "recovery"
            else "ok"
        ),
        current_condition=(
            "ok"
            if event == "recovery"
            else "threshold"
        ),
        event=event,
    )


class ReportTests(unittest.TestCase):
    def test_short_hostname_strips_domain(self):
        with patch(
            "diskcapd.report.socket.gethostname",
            return_value="server01.example.internal",
        ):
            self.assertEqual(
                short_hostname(),
                "server01",
            )

    def test_alert_subject_contains_short_hostname(self):
        with patch(
            "diskcapd.report.socket.gethostname",
            return_value="server01.example.internal",
        ):
            subject, _, _ = build_transition_notification(
                [make_status()],
                [make_transition()],
            )

        self.assertEqual(
            subject,
            "[diskcapd] ALERT server01: /",
        )

    def test_recovery_subject_contains_hostname(self):
        with patch(
            "diskcapd.report.socket.gethostname",
            return_value="server01",
        ):
            subject, _, _ = build_transition_notification(
                [make_status(used_percent=10.0)],
                [make_transition(event="recovery")],
            )

        self.assertEqual(
            subject,
            "[diskcapd] RECOVERY server01: /",
        )

    def test_html_contains_monitored_filesystem_table(self):
        statuses = [
            make_status(
                mountpoint="/",
                source="/dev/mapper/vg-root",
            ),
            make_status(
                mountpoint="/boot",
                source="/dev/nvme0n1p2",
                used_percent=20.0,
            ),
        ]

        with patch(
            "diskcapd.report.socket.gethostname",
            return_value="server01",
        ):
            _, body, html_body = (
                build_transition_notification(
                    statuses,
                    [make_transition()],
                )
            )

        self.assertIn("Filesystem status", body)
        self.assertIn("/dev/mapper/vg-root", html_body)
        self.assertIn("/dev/nvme0n1p2", html_body)
        self.assertIn("server01", html_body)

    def test_html_escapes_dynamic_values(self):
        status = make_status(
            mountpoint="/srv/<danger>",
            source="/dev/test&disk",
        )

        transition = StateTransition(
            mountpoint="/srv/<danger>",
            uuid="test-uuid",
            previous_condition="ok",
            current_condition="threshold",
            event="alert",
        )

        with patch(
            "diskcapd.report.socket.gethostname",
            return_value="host<script>",
        ):
            _, _, html_body = (
                build_transition_notification(
                    [status],
                    [transition],
                )
            )

        self.assertIn(
            "host&lt;script&gt;",
            html_body,
        )
        self.assertIn(
            "/srv/&lt;danger&gt;",
            html_body,
        )
        self.assertIn(
            "/dev/test&amp;disk",
            html_body,
        )
        self.assertNotIn(
            "<script>",
            html_body,
        )

    def test_reminder_subject_and_html_badge(self):
        transition = StateTransition(
            mountpoint="/",
            uuid="test-uuid",
            previous_condition="threshold",
            current_condition="threshold",
            event="reminder",
        )

        with patch(
            "diskcapd.report.socket.gethostname",
            return_value="server01.example.internal",
        ):
            subject, body, html_body = (
                build_transition_notification(
                    [make_status()],
                    [transition],
                )
            )

        self.assertEqual(
            subject,
            "[diskcapd] REMINDER server01: /",
        )
        self.assertIn("REMINDER /", body)
        self.assertIn("badge-reminder", html_body)


if __name__ == "__main__":
    unittest.main()
