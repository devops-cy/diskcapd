"""Discovery of mounted local block-backed filesystems."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from typing import Optional


class DiscoveryError(RuntimeError):
    """Filesystem discovery could not be completed safely."""


@dataclass(frozen=True)
class Filesystem:
    source: str
    device: str
    target: str
    fstype: str
    uuid: Optional[str]
    total_bytes: int
    used_bytes: int
    available_bytes: int
    used_percent: float


def device_path(source: str) -> Optional[str]:
    """Return the real block-device path represented by a findmnt source."""

    if not source.startswith("/dev/"):
        return None

    # Btrfs subvolumes may appear as:
    # /dev/nvme0n1p2[/@]
    device = source.split("[", 1)[0]

    try:
        mode = os.stat(device).st_mode
    except OSError:
        return None

    if not stat.S_ISBLK(mode):
        return None

    return device


def read_usage(target: str) -> tuple[int, int, int, float]:
    """Read filesystem capacity directly from the mounted filesystem."""

    try:
        values = os.statvfs(target)
    except OSError as exc:
        raise DiscoveryError(
            f"Unable to read filesystem usage for {target}: {exc}"
        ) from exc

    block_size = values.f_frsize or values.f_bsize

    total = values.f_blocks * block_size
    free = values.f_bfree * block_size
    available = values.f_bavail * block_size
    used = total - free

    denominator = used + available

    if denominator > 0:
        used_percent = (used / denominator) * 100
    else:
        used_percent = 0.0

    return total, used, available, used_percent


def discover_filesystems() -> list[Filesystem]:
    """Discover writable mounted filesystems backed by local block devices."""

    if shutil.which("findmnt") is None:
        raise DiscoveryError("Required command not found: findmnt")

    command = [
        "findmnt",
        "--json",
        "--list",
        "--evaluate",
        "--output",
        "SOURCE,TARGET,FSTYPE,OPTIONS,UUID",
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "findmnt failed"
        raise DiscoveryError(detail) from exc

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DiscoveryError("findmnt returned invalid JSON") from exc

    discovered: list[Filesystem] = []
    seen: set[tuple[str, str]] = set()

    for row in payload.get("filesystems", []):
        source = str(row.get("source") or "")
        target = str(row.get("target") or "")
        fstype = str(row.get("fstype") or "")

        uuid_value = row.get("uuid")
        uuid = str(uuid_value).strip() if uuid_value else None

        options = {
            option.strip()
            for option in str(row.get("options") or "").split(",")
            if option.strip()
        }

        if not source or not target:
            continue

        if "ro" in options:
            continue

        device = device_path(source)

        if device is None:
            continue

        identity = (source, target)

        if identity in seen:
            continue

        seen.add(identity)

        total, used, available, used_percent = read_usage(target)

        discovered.append(
            Filesystem(
                source=source,
                device=device,
                target=target,
                fstype=fstype,
                uuid=uuid,
                total_bytes=total,
                used_bytes=used,
                available_bytes=available,
                used_percent=used_percent,
            )
        )

    discovered.sort(
        key=lambda filesystem: (
            filesystem.target != "/",
            filesystem.target,
        )
    )

    return discovered
