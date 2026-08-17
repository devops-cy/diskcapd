"""Runtime filesystem monitoring for diskcapd."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Optional

from .config import FilesystemConfig
from .discovery import device_path, read_usage


class MonitoringError(RuntimeError):
    """A filesystem could not be evaluated safely."""


@dataclass(frozen=True)
class FilesystemStatus:
    config: FilesystemConfig
    mounted: bool
    block_backed: bool
    current_source: Optional[str]
    current_uuid: Optional[str]
    current_fstype: Optional[str]
    total_bytes: Optional[int]
    used_bytes: Optional[int]
    available_bytes: Optional[int]
    used_percent: Optional[float]
    problem: Optional[str]

    @property
    def threshold_exceeded(self) -> bool:
        if self.used_percent is None:
            return False

        return self.used_percent >= self.config.threshold

    @property
    def violation(self) -> bool:
        return (
            not self.mounted
            or not self.block_backed
            or self.problem is not None
            or self.threshold_exceeded
        )


def _find_exact_mount(
    mountpoint: str,
) -> Optional[tuple[str, str, Optional[str]]]:
    """Return source, filesystem type and UUID for an exact mountpoint."""

    command = [
        "findmnt",
        "--json",
        "--mountpoint",
        mountpoint,
        "--evaluate",
        "--output",
        "SOURCE,TARGET,FSTYPE,UUID",
    ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise MonitoringError(
            f"Unable to execute findmnt: {exc}"
        ) from exc

    if result.returncode == 1:
        return None

    if result.returncode != 0:
        detail = result.stderr.strip() or "findmnt failed"
        raise MonitoringError(detail)

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MonitoringError(
            "findmnt returned invalid JSON"
        ) from exc

    rows = payload.get("filesystems", [])

    if not rows:
        return None

    row = rows[0]

    target = str(row.get("target") or "")

    # Critical protection against parent-filesystem fallback.
    if target != mountpoint:
        return None

    source = str(row.get("source") or "")
    fstype = str(row.get("fstype") or "")

    uuid_value = row.get("uuid")
    uuid = str(uuid_value).strip() if uuid_value else None

    if not source or not fstype:
        raise MonitoringError(
            f"Incomplete mount information for {mountpoint}"
        )

    return source, fstype, uuid


def evaluate_filesystem(
    config: FilesystemConfig,
) -> FilesystemStatus:
    """Evaluate one configured filesystem."""

    mount = _find_exact_mount(config.mountpoint)

    if mount is None:
        return FilesystemStatus(
            config=config,
            mounted=False,
            block_backed=False,
            current_source=None,
            current_uuid=None,
            current_fstype=None,
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            used_percent=None,
            problem="configured mountpoint is not mounted",
        )

    current_source, current_fstype, current_uuid = mount

    if device_path(current_source) is None:
        return FilesystemStatus(
            config=config,
            mounted=True,
            block_backed=False,
            current_source=current_source,
            current_uuid=current_uuid,
            current_fstype=current_fstype,
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            used_percent=None,
            problem="mounted filesystem is not backed by a local block device",
        )

    if current_uuid is None:
        return FilesystemStatus(
            config=config,
            mounted=True,
            block_backed=True,
            current_source=current_source,
            current_uuid=None,
            current_fstype=current_fstype,
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            used_percent=None,
            problem="mounted filesystem has no detectable UUID",
        )

    if current_uuid != config.uuid:
        return FilesystemStatus(
            config=config,
            mounted=True,
            block_backed=True,
            current_source=current_source,
            current_uuid=current_uuid,
            current_fstype=current_fstype,
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            used_percent=None,
            problem=(
                "unexpected filesystem mounted "
                f"(expected UUID {config.uuid}, current UUID {current_uuid})"
            ),
        )

    try:
        total, used, available, used_percent = read_usage(
            config.mountpoint
        )
    except Exception as exc:
        return FilesystemStatus(
            config=config,
            mounted=True,
            block_backed=True,
            current_source=current_source,
            current_uuid=current_uuid,
            current_fstype=current_fstype,
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            used_percent=None,
            problem=f"unable to read capacity: {exc}",
        )

    return FilesystemStatus(
        config=config,
        mounted=True,
        block_backed=True,
        current_source=current_source,
        current_uuid=current_uuid,
        current_fstype=current_fstype,
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        used_percent=used_percent,
        problem=None,
    )


def evaluate_filesystems(
    filesystems: list[FilesystemConfig],
) -> list[FilesystemStatus]:
    """Evaluate all configured filesystems."""

    return [
        evaluate_filesystem(filesystem)
        for filesystem in filesystems
    ]
