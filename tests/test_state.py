"""Tests for diskcapd persistent monitoring state."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from diskcapd.config import FilesystemConfig
from diskcapd.monitor import FilesystemStatus
from diskcapd.state import (
    CONDITION_MISSING,
    CONDITION_OK,
    CONDITION_THRESHOLD,
    StateRecord,
    evaluate_transitions,
    read_state,
    record_notification_successes,
    state_changed,
    write_state,
)


NOW = datetime(
    2026,
    8,
    17,
    12,
    0,
    tzinfo=timezone.utc,
)


def make_status(
    *,
    used_percent=10.0,
    mounted=True,
    problem=None,
):
    config = FilesystemConfig(
        mountpoint="/mnt/data",
        uuid="expected-uuid",
        source="/dev/sda1",
        fstype="ext4",
        threshold=65,
    )

    return FilesystemStatus(
        config=config,
        mounted=mounted,
        block_backed=mounted,
        current_source="/dev/sda1" if mounted else None,
        current_uuid="expected-uuid" if mounted else None,
        current_fstype="ext4" if mounted else None,
        total_bytes=1000 if mounted else None,
        used_bytes=650 if mounted else None,
        available_bytes=350 if mounted else None,
        used_percent=used_percent if mounted else None,
        problem=problem,
    )


class StateTests(unittest.TestCase):
    def test_state_round_trip(self):
        records = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_OK,
                used_percent=10.0,
            )
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"

            write_state(path, records)
            loaded = read_state(path)

        self.assertEqual(loaded, records)

    def test_first_healthy_run_has_no_event(self):
        current, transitions = evaluate_transitions(
            [make_status()],
            {},
        )

        self.assertEqual(
            current["/mnt/data"].condition,
            CONDITION_OK,
        )
        self.assertIsNone(transitions[0].event)

    def test_first_violation_generates_alert(self):
        _, transitions = evaluate_transitions(
            [make_status(used_percent=70.0)],
            {},
        )

        self.assertEqual(
            transitions[0].current_condition,
            CONDITION_THRESHOLD,
        )
        self.assertEqual(transitions[0].event, "alert")

    def test_repeated_violation_is_silent(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_THRESHOLD,
                used_percent=70.0,
                last_notification_at=NOW - timedelta(hours=1),
            )
        }

        _, transitions = evaluate_transitions(
            [make_status(used_percent=75.0)],
            previous,
            now=NOW,
        )

        self.assertIsNone(transitions[0].event)

    def test_recovery_generates_recovery_event(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_THRESHOLD,
                used_percent=70.0,
            )
        }

        _, transitions = evaluate_transitions(
            [make_status(used_percent=20.0)],
            previous,
        )

        self.assertEqual(transitions[0].event, "recovery")

    def test_missing_mount_generates_alert(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_OK,
                used_percent=20.0,
            )
        }

        status = make_status(
            mounted=False,
            problem="configured mountpoint is not mounted",
        )

        _, transitions = evaluate_transitions(
            [status],
            previous,
        )

        self.assertEqual(
            transitions[0].current_condition,
            CONDITION_MISSING,
        )
        self.assertEqual(transitions[0].event, "alert")

    def test_changed_violation_generates_new_alert(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_THRESHOLD,
                used_percent=70.0,
                last_notification_at=NOW - timedelta(minutes=5),
            )
        }

        status = make_status(
            mounted=False,
            problem="configured mountpoint is not mounted",
        )

        _, transitions = evaluate_transitions(
            [status],
            previous,
        )

        self.assertEqual(
            transitions[0].current_condition,
            CONDITION_MISSING,
        )
        self.assertEqual(transitions[0].event, "alert")


    def test_legacy_state_without_notification_timestamp_is_readable(self):
        content = """{
  "format_version": 1,
  "filesystems": {
    "/mnt/data": {
      "uuid": "expected-uuid",
      "condition": "threshold",
      "used_percent": 70.0
    }
  }
}
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(content)

            loaded = read_state(path)

        self.assertIsNone(
            loaded["/mnt/data"].last_notification_at
        )

    def test_violation_generates_reminder_after_24_hours(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_THRESHOLD,
                used_percent=70.0,
                last_notification_at=NOW - timedelta(hours=24),
            )
        }

        _, transitions = evaluate_transitions(
            [make_status(used_percent=75.0)],
            previous,
            now=NOW,
        )

        self.assertEqual(
            transitions[0].event,
            "reminder",
        )

    def test_missing_mount_generates_reminder_after_24_hours(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_MISSING,
                used_percent=None,
                last_notification_at=NOW - timedelta(hours=24),
            )
        }

        status = make_status(
            mounted=False,
            problem="configured mountpoint is not mounted",
        )

        _, transitions = evaluate_transitions(
            [status],
            previous,
            now=NOW,
        )

        self.assertEqual(
            transitions[0].event,
            "reminder",
        )

    def test_successful_notification_updates_reminder_clock(self):
        current, transitions = evaluate_transitions(
            [make_status(used_percent=70.0)],
            {},
            now=NOW,
        )

        updated = record_notification_successes(
            current,
            transitions,
            NOW,
        )

        self.assertEqual(
            updated["/mnt/data"].last_notification_at,
            NOW,
        )

    def test_notification_timestamp_change_requires_state_write(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_THRESHOLD,
                used_percent=70.0,
                last_notification_at=NOW - timedelta(days=1),
            )
        }

        current = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_THRESHOLD,
                used_percent=75.0,
                last_notification_at=NOW,
            )
        }

        self.assertTrue(
            state_changed(previous, current)
        )

    def test_usage_change_alone_does_not_change_persistent_state(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_OK,
                used_percent=10.0,
            )
        }

        current = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_OK,
                used_percent=20.0,
            )
        }

        self.assertFalse(
            state_changed(previous, current)
        )

    def test_condition_change_requires_state_write(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_OK,
                used_percent=10.0,
            )
        }

        current = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_THRESHOLD,
                used_percent=70.0,
            )
        }

        self.assertTrue(
            state_changed(previous, current)
        )

    def test_uuid_change_requires_state_write(self):
        previous = {
            "/mnt/data": StateRecord(
                uuid="old-uuid",
                condition=CONDITION_OK,
                used_percent=10.0,
            )
        }

        current = {
            "/mnt/data": StateRecord(
                uuid="new-uuid",
                condition=CONDITION_OK,
                used_percent=10.0,
            )
        }

        self.assertTrue(
            state_changed(previous, current)
        )

    def test_mountpoint_set_change_requires_state_write(self):
        previous = {}

        current = {
            "/mnt/data": StateRecord(
                uuid="expected-uuid",
                condition=CONDITION_OK,
                used_percent=10.0,
            )
        }

        self.assertTrue(
            state_changed(previous, current)
        )


if __name__ == "__main__":
    unittest.main()
