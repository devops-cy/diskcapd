"""Notification delivery through the external Postout command."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


SYSTEM_PROFILE_NAME = "diskcapd"
SYSTEM_DISPLAY_NAME = "[diskcapd]"
SYSTEM_PROFILES_FILE = "/etc/postout/profiles.json"


class NotificationError(RuntimeError):
    """A notification operation failed."""


@dataclass(frozen=True)
class NotificationResult:
    recipient: str


def postout_path() -> Optional[str]:
    """Return the installed Postout executable path."""

    return shutil.which("postout")


def system_profile_available() -> bool:
    """Return whether the required diskcapd system profile is available."""

    executable = postout_path()

    if executable is None:
        raise NotificationError(
            "postout executable was not found in PATH"
        )

    try:
        result = subprocess.run(
            [
                executable,
                "--profiles-file",
                SYSTEM_PROFILES_FILE,
                "--profile-list",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise NotificationError(
            f"Unable to execute Postout: {exc}"
        ) from exc

    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"Postout exited with status {result.returncode}"
        )

        raise NotificationError(
            f"Unable to inspect Postout system profiles: {detail}"
        )

    for line in result.stdout.splitlines():
        fields = line.split()

        if fields and fields[0] == SYSTEM_PROFILE_NAME:
            return True

    return False


def configure_system_profile() -> None:
    """Open Postout system configuration interactively."""

    executable = postout_path()

    if executable is None:
        raise NotificationError(
            "postout executable was not found in PATH"
        )

    if os.geteuid() == 0:
        command = [
            executable,
            "config",
            "--system",
            "--profile",
            SYSTEM_PROFILE_NAME,
            "--display-name",
            SYSTEM_DISPLAY_NAME,
        ]
    else:
        sudo = shutil.which("sudo")

        if sudo is None:
            raise NotificationError(
                "sudo is required to configure Postout system profiles"
            )

        command = [
            sudo,
            executable,
            "config",
            "--system",
            "--profile",
            SYSTEM_PROFILE_NAME,
            "--display-name",
            SYSTEM_DISPLAY_NAME,
        ]

    try:
        result = subprocess.run(
            command,
            check=False,
        )
    except OSError as exc:
        raise NotificationError(
            f"Unable to start Postout system configuration: {exc}"
        ) from exc

    if result.returncode != 0:
        raise NotificationError(
            "Postout system configuration did not complete successfully "
            f"(exit {result.returncode})"
        )


def send_notification(
    *,
    recipient: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
) -> NotificationResult:
    """Send one notification through the diskcapd system profile."""

    executable = postout_path()

    if executable is None:
        raise NotificationError(
            "postout executable was not found in PATH"
        )

    recipient = recipient.strip()

    if not recipient:
        raise NotificationError(
            "Notification recipient is required"
        )

    command = [
        executable,
        "--profiles-file",
        SYSTEM_PROFILES_FILE,
        "--profile",
        SYSTEM_PROFILE_NAME,
        "--to",
        recipient,
        "--subject",
        subject,
    ]

    run_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "check": False,
    }

    if html_body is None:
        command.extend(
            [
                "--body",
                body,
            ]
        )
    else:
        command.extend(
            [
                "--html",
                "--body-file",
                "-",
                "--text-fallback",
                body,
            ]
        )

        run_kwargs["input"] = html_body

    try:
        result = subprocess.run(
            command,
            **run_kwargs,
        )
    except OSError as exc:
        raise NotificationError(
            f"Unable to execute Postout: {exc}"
        ) from exc

    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"Postout exited with status {result.returncode}"
        )

        raise NotificationError(
            f"Postout delivery failed: {detail}"
        )

    return NotificationResult(
        recipient=recipient,
    )
