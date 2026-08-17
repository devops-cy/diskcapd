"""Human-friendly diskcapd notification reports."""

from __future__ import annotations

import html
import socket
from pathlib import Path

from . import __version__
from .monitor import FilesystemStatus
from .state import CONDITION_OK, StateTransition


_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "templates"
    / "notification.html"
)


def short_hostname() -> str:
    """Return the local short hostname without domain information."""

    hostname = socket.gethostname().strip()

    if not hostname:
        return "unknown-host"

    return hostname.split(".", 1)[0]


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "-"

    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    amount = float(value)

    for unit in units:
        if abs(amount) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"

            return f"{amount:.1f} {unit}"

        amount /= 1024.0

    return f"{value} B"


def _status_label(status: FilesystemStatus) -> str:
    if status.problem is not None:
        return "VIOLATION"

    if status.threshold_exceeded:
        return "ALERT"

    return "OK"


def _event_label(events: list[StateTransition]) -> str:
    event_types = {
        transition.event
        for transition in events
        if transition.event is not None
    }

    labels = [
        event.upper()
        for event in (
            "alert",
            "reminder",
            "recovery",
        )
        if event in event_types
    ]

    return "/".join(labels) or "NOTIFICATION"


def _plain_status_table(
    statuses: list[FilesystemStatus],
) -> list[str]:
    rows = [
        (
            f"{'Mount':<16}"
            f"{'Type':<9}"
            f"{'Size':>11}"
            f"{'Used':>11}"
            f"{'Avail':>11}"
            f"{'Use%':>8}"
            f"{'Limit':>8}"
            f"  Status"
        ),
        "-" * 86,
    ]

    for status in statuses:
        used_percent = (
            f"{status.used_percent:.1f}%"
            if status.used_percent is not None
            else "-"
        )

        rows.append(
            f"{status.config.mountpoint:<16}"
            f"{status.config.fstype:<9}"
            f"{_format_bytes(status.total_bytes):>11}"
            f"{_format_bytes(status.used_bytes):>11}"
            f"{_format_bytes(status.available_bytes):>11}"
            f"{used_percent:>8}"
            f"{str(status.config.threshold) + '%':>8}"
            f"  {_status_label(status)}"
        )

    return rows


def _html_event_rows(
    statuses: list[FilesystemStatus],
    events: list[StateTransition],
) -> str:
    status_by_mountpoint = {
        status.config.mountpoint: status
        for status in statuses
    }

    rows: list[str] = []

    for transition in events:
        status = status_by_mountpoint.get(
            transition.mountpoint
        )

        if transition.event == "recovery":
            condition = (
                f"{transition.previous_condition} -> "
                f"{CONDITION_OK}"
            )
        else:
            condition = transition.current_condition

        used = "-"

        if status is not None and status.used_percent is not None:
            used = f"{status.used_percent:.1f}%"

        threshold = "-"

        if status is not None:
            threshold = f"{status.config.threshold}%"

        rows.append(
            "<tr>"
            f"<td>{html.escape(transition.mountpoint)}</td>"
            f"<td>{html.escape(condition)}</td>"
            f"<td>{html.escape(used)}</td>"
            f"<td>{html.escape(threshold)}</td>"
            "</tr>"
        )

    return "\n".join(rows)


def _html_filesystem_rows(
    statuses: list[FilesystemStatus],
) -> str:
    rows: list[str] = []

    for status in statuses:
        source = (
            status.current_source
            or status.config.source
            or "-"
        )

        used_percent = (
            f"{status.used_percent:.1f}%"
            if status.used_percent is not None
            else "-"
        )

        status_label = _status_label(status)

        if status_label == "OK":
            status_class = "status-ok"
        elif status_label == "ALERT":
            status_class = "status-alert"
        else:
            status_class = "status-violation"

        rows.append(
            "<tr>"
            f"<td>{html.escape(status.config.mountpoint)}</td>"
            f"<td>{html.escape(source)}</td>"
            f"<td>{html.escape(status.config.fstype)}</td>"
            f"<td>{html.escape(_format_bytes(status.total_bytes))}</td>"
            f"<td>{html.escape(_format_bytes(status.used_bytes))}</td>"
            f"<td>{html.escape(_format_bytes(status.available_bytes))}</td>"
            f"<td>{html.escape(used_percent)}</td>"
            f"<td>{status.config.threshold}%</td>"
            f'<td class="{status_class}">'
            f"{html.escape(status_label)}</td>"
            "</tr>"
        )

    return "\n".join(rows)


def build_transition_notification(
    statuses: list[FilesystemStatus],
    events: list[StateTransition],
) -> tuple[str, str, str]:
    """Build subject, plain text and HTML for one monitoring event."""

    hostname = short_hostname()
    label = _event_label(events)

    mountpoints = ", ".join(
        transition.mountpoint
        for transition in events
    )

    subject = (
        f"[diskcapd] {label} {hostname}: "
        f"{mountpoints}"
    )

    status_by_mountpoint = {
        status.config.mountpoint: status
        for status in statuses
    }

    lines = [
        "diskcapd filesystem notification",
        "",
        f"Host: {hostname}",
        f"Event: {label}",
        "",
    ]

    for transition in events:
        status = status_by_mountpoint.get(
            transition.mountpoint
        )

        lines.append(
            f"{transition.event.upper()} "
            f"{transition.mountpoint}"
        )

        if transition.event == "recovery":
            lines.append(
                "Condition: "
                f"{transition.previous_condition} -> "
                f"{CONDITION_OK}"
            )
        else:
            lines.append(
                f"Condition: "
                f"{transition.current_condition}"
            )

        if status is not None:
            if status.used_percent is not None:
                lines.append(
                    f"Used: {status.used_percent:.1f}%"
                )

            lines.append(
                f"Threshold: "
                f"{status.config.threshold}%"
            )

        lines.append("")

    lines.append("Filesystem status")
    lines.append("")
    lines.extend(_plain_status_table(statuses))

    body = "\n".join(lines).rstrip() + "\n"

    template = _TEMPLATE_PATH.read_text(
        encoding="utf-8"
    )

    if label == "RECOVERY":
        badge_class = "badge-recovery"
    elif label == "REMINDER":
        badge_class = "badge-reminder"
    else:
        badge_class = "badge-alert"

    html_body = template

    replacements = {
        "@@HOSTNAME@@": html.escape(hostname),
        "@@EVENT_LABEL@@": html.escape(label),
        "@@BADGE_CLASS@@": badge_class,
        "@@EVENT_ROWS@@": _html_event_rows(
            statuses,
            events,
        ),
        "@@FILESYSTEM_ROWS@@": _html_filesystem_rows(
            statuses
        ),
        "@@VERSION@@": html.escape(__version__),
    }

    for token, value in replacements.items():
        html_body = html_body.replace(
            token,
            value,
        )

    return subject, body, html_body
