"""Persistent monitoring state for diskcapd."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

from .monitor import FilesystemStatus


STATE_FORMAT_VERSION = 1
REMINDER_INTERVAL = timedelta(hours=24)

CONDITION_OK = "ok"
CONDITION_THRESHOLD = "threshold"
CONDITION_MISSING = "missing"
CONDITION_NOT_BLOCK = "not_block_backed"
CONDITION_UUID_MISSING = "uuid_missing"
CONDITION_WRONG_UUID = "wrong_uuid"
CONDITION_ERROR = "error"


class StateError(RuntimeError):
    """Persistent monitoring state could not be processed safely."""


@dataclass(frozen=True)
class StateRecord:
    uuid: str
    condition: str
    used_percent: Optional[float]
    last_notification_at: Optional[datetime] = None


@dataclass(frozen=True)
class StateTransition:
    mountpoint: str
    uuid: str
    previous_condition: Optional[str]
    current_condition: str
    event: Optional[str]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""

    return datetime.now(timezone.utc)


def _normalize_timestamp(
    value: datetime,
    description: str,
) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StateError(
            f"{description} must include timezone information."
        )

    return value.astimezone(timezone.utc)


def _parse_timestamp(
    value,
    mountpoint: str,
) -> Optional[datetime]:
    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise StateError(
            f"State record for {mountpoint} has an invalid "
            "notification timestamp."
        )

    text = value.strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StateError(
            f"State record for {mountpoint} has an invalid "
            "notification timestamp."
        ) from exc

    return _normalize_timestamp(
        parsed,
        f"Notification timestamp for {mountpoint}",
    )


def _format_timestamp(
    value: Optional[datetime],
) -> Optional[str]:
    if value is None:
        return None

    normalized = _normalize_timestamp(
        value,
        "Notification timestamp",
    )

    return normalized.isoformat().replace(
        "+00:00",
        "Z",
    )


def condition_for_status(status: FilesystemStatus) -> str:
    """Convert runtime filesystem status into a stable condition."""

    if not status.mounted:
        return CONDITION_MISSING

    if not status.block_backed:
        return CONDITION_NOT_BLOCK

    if status.current_uuid is None:
        return CONDITION_UUID_MISSING

    if status.current_uuid != status.config.uuid:
        return CONDITION_WRONG_UUID

    if status.problem is not None:
        return CONDITION_ERROR

    if status.threshold_exceeded:
        return CONDITION_THRESHOLD

    return CONDITION_OK


def read_state(path: Path) -> Dict[str, StateRecord]:
    """Read previous diskcapd state.

    A missing file represents a fresh monitor with no prior state.
    """

    if not path.exists():
        return {}

    if not path.is_file():
        raise StateError(f"State path is not a file: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"Unable to read state: {exc}") from exc

    if payload.get("format_version") != STATE_FORMAT_VERSION:
        raise StateError("Unsupported state file format.")

    filesystems = payload.get("filesystems")

    if not isinstance(filesystems, dict):
        raise StateError("State file has invalid filesystem data.")

    records: Dict[str, StateRecord] = {}

    for mountpoint, values in filesystems.items():
        if not isinstance(mountpoint, str) or not isinstance(values, dict):
            raise StateError(
                "State file contains an invalid filesystem record."
            )

        uuid = values.get("uuid")
        condition = values.get("condition")
        used_percent = values.get("used_percent")
        last_notification_at = _parse_timestamp(
            values.get("last_notification_at"),
            mountpoint,
        )

        if not isinstance(uuid, str) or not uuid:
            raise StateError(
                f"State record for {mountpoint} has an invalid UUID."
            )

        if not isinstance(condition, str) or not condition:
            raise StateError(
                f"State record for {mountpoint} has an invalid condition."
            )

        if used_percent is not None and not isinstance(
            used_percent,
            (int, float),
        ):
            raise StateError(
                f"State record for {mountpoint} has invalid usage data."
            )

        records[mountpoint] = StateRecord(
            uuid=uuid,
            condition=condition,
            used_percent=(
                float(used_percent)
                if used_percent is not None
                else None
            ),
            last_notification_at=last_notification_at,
        )

    return records


def state_changed(
    previous: Dict[str, StateRecord],
    current: Dict[str, StateRecord],
) -> bool:
    """Return whether monitoring state changed meaningfully.

    Usage percentage alone does not require persistence. Persistent state
    tracks monitoring identity, condition and notification accountability.
    """

    if previous.keys() != current.keys():
        return True

    for mountpoint, record in current.items():
        old = previous.get(mountpoint)

        if old is None:
            return True

        if old.uuid != record.uuid:
            return True

        if old.condition != record.condition:
            return True

        if old.last_notification_at != record.last_notification_at:
            return True

    return False


def write_state(
    path: Path,
    records: Dict[str, StateRecord],
) -> None:
    """Write diskcapd state atomically."""

    payload = {
        "format_version": STATE_FORMAT_VERSION,
        "filesystems": {
            mountpoint: {
                "uuid": record.uuid,
                "condition": record.condition,
                "used_percent": record.used_percent,
                "last_notification_at": _format_timestamp(
                    record.last_notification_at
                ),
            }
            for mountpoint, record in sorted(records.items())
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )

    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

        temporary_path.chmod(0o600)
        temporary_path.replace(path)

    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _reminder_due(
    record: StateRecord,
    now: datetime,
) -> bool:
    if record.last_notification_at is None:
        return True

    last_notification_at = _normalize_timestamp(
        record.last_notification_at,
        "Last notification timestamp",
    )

    return (
        now - last_notification_at
        >= REMINDER_INTERVAL
    )


def evaluate_transitions(
    statuses: list[FilesystemStatus],
    previous: Dict[str, StateRecord],
    *,
    now: Optional[datetime] = None,
) -> tuple[Dict[str, StateRecord], list[StateTransition]]:
    """Evaluate alerts, reminders and recoveries."""

    if now is None:
        now = utc_now()

    now = _normalize_timestamp(
        now,
        "Current monitoring time",
    )

    current: Dict[str, StateRecord] = {}
    transitions: list[StateTransition] = []

    for status in statuses:
        mountpoint = status.config.mountpoint
        uuid = status.config.uuid
        condition = condition_for_status(status)

        old = previous.get(mountpoint)

        # A configuration change to a different expected UUID starts a
        # fresh monitoring identity at this mountpoint.
        if old is not None and old.uuid != uuid:
            old = None

        previous_condition = (
            old.condition
            if old is not None
            else None
        )

        event: Optional[str] = None

        if condition == CONDITION_OK:
            if (
                previous_condition is not None
                and previous_condition != CONDITION_OK
            ):
                event = "recovery"

        elif previous_condition != condition:
            event = "alert"

        elif old is not None and _reminder_due(old, now):
            event = "reminder"

        if (
            condition != CONDITION_OK
            and old is not None
            and previous_condition == condition
        ):
            last_notification_at = old.last_notification_at
        else:
            last_notification_at = None

        transitions.append(
            StateTransition(
                mountpoint=mountpoint,
                uuid=uuid,
                previous_condition=previous_condition,
                current_condition=condition,
                event=event,
            )
        )

        current[mountpoint] = StateRecord(
            uuid=uuid,
            condition=condition,
            used_percent=status.used_percent,
            last_notification_at=last_notification_at,
        )

    return current, transitions


def record_notification_successes(
    records: Dict[str, StateRecord],
    transitions: list[StateTransition],
    notified_at: datetime,
) -> Dict[str, StateRecord]:
    """Record successfully submitted violation notifications."""

    notified_at = _normalize_timestamp(
        notified_at,
        "Notification time",
    )

    updated = dict(records)

    for transition in transitions:
        if transition.event not in {"alert", "reminder"}:
            continue

        record = updated.get(transition.mountpoint)

        if record is None:
            continue

        if record.uuid != transition.uuid:
            continue

        updated[transition.mountpoint] = StateRecord(
            uuid=record.uuid,
            condition=record.condition,
            used_percent=record.used_percent,
            last_notification_at=notified_at,
        )

    return updated
