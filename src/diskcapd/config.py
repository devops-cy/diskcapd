"""Configuration handling for diskcapd."""

from __future__ import annotations

import configparser
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_THRESHOLD = 65
FORMAT_VERSION = "2"


class ConfigurationError(RuntimeError):
    """diskcapd configuration could not be processed safely."""


@dataclass(frozen=True)
class FilesystemConfig:
    mountpoint: str
    uuid: str
    source: str
    fstype: str
    threshold: int


def write_configuration(
    path: Path,
    filesystems: list[FilesystemConfig],
    notification_recipient: str = "",
) -> None:
    """Write a diskcapd configuration atomically."""

    parser = configparser.ConfigParser(interpolation=None)

    parser["general"] = {
        "format_version": FORMAT_VERSION,
    }

    notification_recipient = notification_recipient.strip()

    if notification_recipient:
        parser["notifications"] = {
            "recipient": notification_recipient,
        }

    for filesystem in filesystems:
        section = f"filesystem:{filesystem.mountpoint}"

        parser[section] = {
            "mountpoint": filesystem.mountpoint,
            "uuid": filesystem.uuid,
            "source": filesystem.source,
            "filesystem": filesystem.fstype,
            "threshold": str(filesystem.threshold),
        }

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=parent,
        text=True,
    )

    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)

        temporary_path.chmod(0o644)
        temporary_path.replace(path)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise



def read_notification_recipient(path: Path) -> str:
    """Read and validate the configured notification recipient."""

    if not path.is_file():
        raise ConfigurationError(
            f"Configuration file not found: {path}"
        )

    parser = configparser.ConfigParser(interpolation=None)

    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise ConfigurationError(
            f"Unable to read configuration: {exc}"
        ) from exc

    if "notifications" not in parser:
        raise ConfigurationError(
            "Configuration is missing the [notifications] section."
        )

    recipient = parser["notifications"].get(
        "recipient",
        "",
    ).strip()

    if not recipient:
        raise ConfigurationError(
            "Notification recipient is missing."
        )

    return recipient


def read_configuration(path: Path) -> list[FilesystemConfig]:
    """Read and validate a diskcapd configuration."""

    if not path.is_file():
        raise ConfigurationError(
            f"Configuration file not found: {path}"
        )

    parser = configparser.ConfigParser(interpolation=None)

    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise ConfigurationError(
            f"Unable to read configuration: {exc}"
        ) from exc

    if "general" not in parser:
        raise ConfigurationError(
            "Configuration is missing the [general] section."
        )

    format_version = parser["general"].get(
        "format_version",
        "",
    ).strip()

    if format_version != FORMAT_VERSION:
        raise ConfigurationError(
            f"Unsupported configuration format: "
            f"{format_version or 'missing'}. Run diskcapd setup."
        )

    filesystems: list[FilesystemConfig] = []

    for section_name in parser.sections():
        if not section_name.startswith("filesystem:"):
            continue

        section = parser[section_name]

        mountpoint = section.get("mountpoint", "").strip()
        uuid = section.get("uuid", "").strip()
        source = section.get("source", "").strip()
        fstype = section.get("filesystem", "").strip()
        threshold_text = section.get("threshold", "").strip()

        if not mountpoint:
            raise ConfigurationError(
                f"{section_name}: mountpoint is missing."
            )

        if not os.path.isabs(mountpoint):
            raise ConfigurationError(
                f"{section_name}: mountpoint must be absolute."
            )

        if os.path.normpath(mountpoint) != mountpoint:
            raise ConfigurationError(
                f"{section_name}: mountpoint is not normalized."
            )

        if not uuid:
            raise ConfigurationError(
                f"{section_name}: filesystem UUID is missing."
            )

        if not source:
            raise ConfigurationError(
                f"{section_name}: source is missing."
            )

        if not fstype:
            raise ConfigurationError(
                f"{section_name}: filesystem type is missing."
            )

        try:
            threshold = int(threshold_text)
        except ValueError as exc:
            raise ConfigurationError(
                f"{section_name}: threshold must be a whole percentage."
            ) from exc

        if not 1 <= threshold <= 99:
            raise ConfigurationError(
                f"{section_name}: threshold must be between 1 and 99."
            )

        filesystems.append(
            FilesystemConfig(
                mountpoint=mountpoint,
                uuid=uuid,
                source=source,
                fstype=fstype,
                threshold=threshold,
            )
        )

    if not filesystems:
        raise ConfigurationError(
            "Configuration contains no monitored filesystems."
        )

    return filesystems
