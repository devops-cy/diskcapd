"""Command-line interface for diskcapd."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from . import ui
from .config import (
    DEFAULT_THRESHOLD,
    ConfigurationError,
    FilesystemConfig,
    read_configuration,
    read_notification_recipient,
    write_configuration,
)
from .discovery import DiscoveryError, Filesystem, discover_filesystems
from .monitor import MonitoringError, evaluate_filesystems
from .report import build_transition_notification
from .notify import (
    SYSTEM_PROFILE_NAME,
    NotificationError,
    configure_system_profile,
    send_notification,
    system_profile_available,
)
from .state import (
    CONDITION_OK,
    StateError,
    evaluate_transitions,
    read_state,
    record_notification_successes,
    state_changed,
    utc_now,
    write_state,
)


DEFAULT_CONFIG_PATH = Path("/etc/diskcapd/diskcapd.conf")
DEFAULT_STATE_PATH = Path("/var/lib/diskcapd/state.json")
SYSTEM_TIMER_UNIT = "diskcapd.timer"

def format_bytes(value: int) -> str:
    """Return a compact human-readable byte value."""

    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    amount = float(value)

    for unit in units:
        if abs(amount) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"

            return f"{amount:.1f} {unit}"

        amount /= 1024.0

    return f"{value} B"


def show_filesystem(index: int, filesystem: Filesystem) -> None:
    print()
    print(
        f"  {ui.CYAN}{ui.BOLD}[{index}]{ui.RESET} "
        f"{ui.GREEN}{ui.BOLD}{filesystem.target}{ui.RESET}"
    )
    print()

    ui.kv("Source", filesystem.source)
    ui.kv("UUID", filesystem.uuid or "unavailable")
    ui.kv("Filesystem", filesystem.fstype)
    ui.kv("Capacity", format_bytes(filesystem.total_bytes))

    ui.kv(
        "Used",
        (
            f"{filesystem.used_percent:.1f}% "
            f"({format_bytes(filesystem.used_bytes)})"
        ),
    )

    ui.kv(
        "Available",
        format_bytes(filesystem.available_bytes),
    )


def run_discover() -> int:
    ui.header(__version__)

    ui.info("Scanning mounted local block filesystems...")
    ui.step_pause()

    try:
        filesystems = discover_filesystems()
    except DiscoveryError as exc:
        ui.fail(str(exc))
        return 2

    if not filesystems:
        ui.warn("No eligible local block-backed filesystems were found.")
        return 0

    ui.ok(f"{len(filesystems)} eligible filesystem(s) detected")
    ui.section_pause()

    ui.section("Local filesystems")

    for index, filesystem in enumerate(filesystems, start=1):
        show_filesystem(index, filesystem)

    ui.section("Summary")

    ui.kv("Eligible", str(len(filesystems)))
    ui.kv("Identity", "mountpoint + filesystem UUID")
    ui.kv("Scope", "writable local block filesystems")

    print()
    ui.ok("Filesystem discovery completed")
    print()

    return 0



def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt for a yes/no answer."""

    while True:
        suffix = "[Y/n]" if default else "[y/N]"

        try:
            answer = input(
                f"{ui.BOLD}{prompt} {suffix}:{ui.RESET} "
            ).strip().lower()
        except EOFError:
            raise RuntimeError("Interactive setup requires a terminal")

        if not answer:
            return default

        if answer in {"y", "yes"}:
            return True

        if answer in {"n", "no"}:
            return False

        ui.warn("Please answer y or n.")


def prompt_threshold(default: int = DEFAULT_THRESHOLD) -> int:
    """Prompt for a filesystem warning threshold."""

    while True:
        try:
            answer = input(
                f"{ui.BOLD}Warning threshold [{default}%]:{ui.RESET} "
            ).strip()
        except EOFError:
            raise RuntimeError("Interactive setup requires a terminal")

        if not answer:
            return default

        answer = answer.removesuffix("%").strip()

        try:
            threshold = int(answer)
        except ValueError:
            ui.warn("Enter a whole percentage between 1 and 99.")
            continue

        if not 1 <= threshold <= 99:
            ui.warn("Enter a whole percentage between 1 and 99.")
            continue

        return threshold



def prompt_recipient() -> str:
    """Prompt for the notification recipient."""

    while True:
        try:
            recipient = input(
                f"{ui.BOLD}Notification recipient:{ui.RESET} "
            ).strip()
        except EOFError:
            raise RuntimeError(
                "Interactive setup requires a terminal"
            )

        if recipient:
            return recipient

        ui.warn("Notification recipient cannot be empty.")


def run_notification_setup(recipient: str) -> bool:
    """Configure and verify notification delivery interactively."""

    while True:
        try:
            available = system_profile_available()
        except NotificationError as exc:
            ui.fail(str(exc))
            return False

        if not available:
            ui.warn("Email notifications are not configured")

            print()
            print(
                "  Have your SMTP server details, username and "
                "password/app password ready."
            )
            print()

            try:
                configure = prompt_yes_no(
                    "Configure email notifications now?",
                    default=True,
                )
            except RuntimeError as exc:
                ui.fail(str(exc))
                return False

            if not configure:
                ui.warn("Email notification setup was not completed")
                return False

            print()

            try:
                configure_system_profile()
            except NotificationError as exc:
                ui.fail(str(exc))
                return False

            try:
                available = system_profile_available()
            except NotificationError as exc:
                ui.fail(str(exc))
                return False

            if not available:
                ui.fail(
                    "Email notification configuration "
                    "was not completed"
                )
                return False

        print()
        ui.info(f"Sending test email to {recipient}...")
        ui.step_pause()

        subject = "diskcapd notification test"
        body = (
            "diskcapd notification test\n"
            "\n"
            "This is a test notification from diskcapd.\n"
            "If you received this message, email notifications "
            "are working.\n"
        )

        try:
            send_notification(
                recipient=recipient,
                subject=subject,
                body=body,
            )
        except NotificationError as exc:
            ui.warn("Test email could not be submitted")
            ui.warn(str(exc))
            print()

            try:
                reconfigure = prompt_yes_no(
                    "Reconfigure SMTP settings now?",
                    default=True,
                )
            except RuntimeError as prompt_exc:
                ui.fail(str(prompt_exc))
                return False

            if not reconfigure:
                return False

            print()

            try:
                configure_system_profile()
            except NotificationError as config_exc:
                ui.fail(str(config_exc))
                return False

            continue

        ui.ok("Test email submitted successfully")
        print()

        try:
            received = prompt_yes_no(
                "Did you receive the test email?",
                default=True,
            )
        except RuntimeError as exc:
            ui.fail(str(exc))
            return False

        if received:
            ui.ok("Email notifications verified")
            return True

        print()
        ui.warn("Test email receipt was not confirmed")

        try:
            reconfigure = prompt_yes_no(
                "Reconfigure SMTP settings now?",
                default=True,
            )
        except RuntimeError as exc:
            ui.fail(str(exc))
            return False

        if not reconfigure:
            return False

        print()

        try:
            configure_system_profile()
        except NotificationError as exc:
            ui.fail(str(exc))
            return False


def enable_unattended_monitoring() -> tuple[bool, str]:
    """Enable and start the packaged systemd timer."""

    try:
        result = subprocess.run(
            ["systemctl", "enable", "--now", SYSTEM_TIMER_UNIT],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return False, str(exc)

    if result.returncode == 0:
        return True, ""

    error = result.stderr.strip() or result.stdout.strip()
    return False, error or f"systemctl exited with status {result.returncode}"



def run_setup(config_path: Path) -> int:
    """Interactively configure filesystem and notification monitoring."""

    ui.header(__version__)

    if not sys.stdin.isatty():
        ui.fail("Interactive setup requires a terminal.")
        return 2

    ui.info("Discovering local filesystems...")
    ui.step_pause()

    try:
        filesystems = discover_filesystems()
    except DiscoveryError as exc:
        ui.fail(str(exc))
        return 2

    if not filesystems:
        ui.warn("No eligible local block-backed filesystems were found.")
        return 0

    ui.ok(f"{len(filesystems)} eligible filesystem(s) detected")
    ui.section_pause()

    selected: list[FilesystemConfig] = []

    ui.section("Filesystem selection")

    for index, filesystem in enumerate(filesystems, start=1):
        show_filesystem(index, filesystem)

        print()

        try:
            monitor = prompt_yes_no(
                "Monitor this filesystem?",
                default=True,
            )
        except RuntimeError as exc:
            ui.fail(str(exc))
            return 2

        if not monitor:
            ui.info(f"Skipping {filesystem.target}")
            continue

        if filesystem.uuid is None:
            ui.warn(
                f"{filesystem.target} has no detectable filesystem UUID."
            )
            ui.warn("It cannot be monitored safely by this prototype.")
            continue

        try:
            threshold = prompt_threshold()
        except RuntimeError as exc:
            ui.fail(str(exc))
            return 2

        selected.append(
            FilesystemConfig(
                mountpoint=filesystem.target,
                uuid=filesystem.uuid,
                source=filesystem.source,
                fstype=filesystem.fstype,
                threshold=threshold,
            )
        )

        ui.ok(
            f"{filesystem.target} selected at {threshold}%"
        )

    if not selected:
        print()
        ui.warn("No filesystems were selected.")
        ui.warn("Configuration was not written.")
        return 0

    ui.section("Email notifications")

    try:
        recipient = prompt_recipient()
    except RuntimeError as exc:
        ui.fail(str(exc))
        return 2

    print()
    ui.kv("Recipient", recipient)
    print()

    if not run_notification_setup(recipient):
        print()
        ui.warn("Configuration was not written.")
        ui.warn("Complete email notification setup and try again.")
        return 3

    ui.section("Configuration")

    ui.kv("File", str(config_path))
    ui.kv("Filesystems", str(len(selected)))
    ui.kv("Notifications", recipient)

    for filesystem in selected:
        ui.kv(
            filesystem.mountpoint,
            f"threshold {filesystem.threshold}%",
        )

    print()

    try:
        write_configuration(
            config_path,
            selected,
            notification_recipient=recipient,
        )
    except OSError as exc:
        ui.fail(f"Unable to write configuration: {exc}")
        return 2

    ui.ok("Configuration written successfully")
    print()

    if config_path == DEFAULT_CONFIG_PATH:
        try:
            enable_timer = prompt_yes_no(
                "Enable unattended monitoring now?",
                default=True,
            )
        except RuntimeError as exc:
            ui.fail(str(exc))
            return 2

        if enable_timer:
            enabled, error = enable_unattended_monitoring()

            if not enabled:
                ui.fail(f"Unable to enable {SYSTEM_TIMER_UNIT}")

                if error:
                    ui.warn(error)

                ui.info("Configuration remains valid.")
                ui.info(
                    "Enable monitoring later with: "
                    f"systemctl enable --now {SYSTEM_TIMER_UNIT}"
                )
                return 2

            ui.ok("Unattended monitoring enabled")
        else:
            ui.info("Unattended monitoring remains disabled")
            ui.info(
                "Enable it later with: "
                f"systemctl enable --now {SYSTEM_TIMER_UNIT}"
            )

        print()

    return 0

def load_runtime_status(config_path: Path):
    try:
        configured = read_configuration(config_path)
        return evaluate_filesystems(configured)
    except (ConfigurationError, MonitoringError) as exc:
        ui.fail(str(exc))
        return None


def run_status(config_path: Path) -> int:
    """Show detailed status without sending notifications."""

    ui.header(__version__)

    ui.info(f"Reading configuration from {config_path}...")
    ui.step_pause()

    statuses = load_runtime_status(config_path)

    if statuses is None:
        return 2

    ui.ok(f"{len(statuses)} monitored filesystem(s) loaded")
    ui.section_pause()

    ui.section("Filesystem status")

    violations = 0

    for index, status in enumerate(statuses, start=1):
        print()
        print(
            f"  {ui.CYAN}{ui.BOLD}[{index}]{ui.RESET} "
            f"{ui.GREEN}{ui.BOLD}"
            f"{status.config.mountpoint}"
            f"{ui.RESET}"
        )
        print()

        if status.current_uuid == status.config.uuid:
            ui.kv("UUID", status.config.uuid)
        else:
            ui.kv("Expected UUID", status.config.uuid)

            if status.current_uuid is not None:
                ui.kv("Current UUID", status.current_uuid)

        if status.current_source is not None:
            ui.kv("Source", status.current_source)
        else:
            ui.kv("Last source", status.config.source)

        if status.current_fstype is not None:
            ui.kv("Filesystem", status.current_fstype)

        ui.kv(
            "Threshold",
            f"{status.config.threshold}%",
        )

        if status.used_percent is not None:
            ui.kv(
                "Capacity",
                format_bytes(status.total_bytes or 0),
            )
            ui.kv(
                "Used",
                (
                    f"{status.used_percent:.1f}% "
                    f"({format_bytes(status.used_bytes or 0)})"
                ),
            )
            ui.kv(
                "Available",
                format_bytes(status.available_bytes or 0),
            )

        if status.problem is not None:
            ui.kv(
                "Status",
                f"{ui.RED}{ui.BOLD}VIOLATION{ui.RESET}",
            )
            ui.kv("Problem", status.problem)
            violations += 1

        elif status.threshold_exceeded:
            ui.kv(
                "Status",
                f"{ui.YELLOW}{ui.BOLD}THRESHOLD{ui.RESET}",
            )
            violations += 1

        else:
            ui.kv(
                "Status",
                f"{ui.GREEN}{ui.BOLD}OK{ui.RESET}",
            )

    ui.section("Summary")

    ui.kv("Monitored", str(len(statuses)))
    ui.kv("Healthy", str(len(statuses) - violations))
    ui.kv("Violations", str(violations))

    print()

    if violations:
        ui.warn(f"{violations} filesystem violation(s) detected")
        print()
        return 1

    ui.ok("All monitored filesystems are within limits")
    print()

    return 0



def run_check(
    config_path: Path,
    state_path: Path,
    quiet: bool = False,
) -> int:
    """Perform monitoring, notification and state persistence."""

    if not quiet:
        ui.header(__version__)
        ui.info("Checking configured filesystems...")
        ui.step_pause()

    statuses = load_runtime_status(config_path)

    if statuses is None:
        return 2

    try:
        recipient = read_notification_recipient(
            config_path
        )
    except ConfigurationError as exc:
        ui.fail(str(exc))
        return 2

    try:
        previous_state = read_state(state_path)
    except StateError as exc:
        ui.fail(str(exc))
        return 2

    check_time = utc_now()

    current_state, transitions = evaluate_transitions(
        statuses,
        previous_state,
        now=check_time,
    )

    violations = 0

    if not quiet:
        print()

    for status in statuses:
        mountpoint = status.config.mountpoint

        if status.problem is not None:
            violations += 1

            if not quiet:
                ui.warn(
                    f"{mountpoint}: {status.problem}"
                )

            continue

        if status.used_percent is None:
            violations += 1

            if not quiet:
                ui.warn(
                    f"{mountpoint}: capacity could not be determined"
                )

            continue

        if status.threshold_exceeded:
            violations += 1

            if not quiet:
                ui.warn(
                    f"{mountpoint}: "
                    f"{status.used_percent:.1f}% used, "
                    f"threshold {status.config.threshold}%"
                )

            continue

        if not quiet:
            ui.ok(
                f"{mountpoint}: "
                f"{status.used_percent:.1f}% used, "
                f"threshold {status.config.threshold}%"
            )

    events = [
        transition
        for transition in transitions
        if transition.event is not None
    ]

    if events:
        subject, body, html_body = (
            build_transition_notification(
                statuses,
                events,
            )
        )

        try:
            send_notification(
                recipient=recipient,
                subject=subject,
                body=body,
                html_body=html_body,
            )
        except NotificationError as exc:
            ui.fail(
                f"Unable to submit monitoring notification: {exc}"
            )
            return 3

        current_state = record_notification_successes(
            current_state,
            events,
            check_time,
        )

    if events and not quiet:
        ui.section("State transitions")

    for transition in events:
        if transition.event == "alert":
            message = (
                f"ALERT {transition.mountpoint}: "
                f"{transition.current_condition}"
            )

            if quiet:
                print(message)
            else:
                ui.warn(message)

        elif transition.event == "reminder":
            message = (
                f"REMINDER {transition.mountpoint}: "
                f"{transition.current_condition}"
            )

            if quiet:
                print(message)
            else:
                ui.warn(message)

        elif transition.event == "recovery":
            message = (
                f"RECOVERY {transition.mountpoint}: "
                f"{transition.previous_condition} -> "
                f"{CONDITION_OK}"
            )

            if quiet:
                print(message)
            else:
                ui.ok(message)

    if state_changed(previous_state, current_state):
        try:
            write_state(state_path, current_state)
        except OSError as exc:
            ui.fail(
                f"Unable to write monitoring state: {exc}"
            )
            return 2

    if quiet:
        return 1 if violations else 0

    print()
    ui.kv("State", str(state_path))
    print()

    if violations:
        ui.warn(
            f"{violations} filesystem violation(s) detected"
        )
        print()
        return 1

    ui.ok("Filesystem check completed successfully")
    print()

    return 0



def run_test_notification(recipient: str) -> int:
    """Verify configuration and send a diskcapd test notification."""

    ui.header(__version__)

    ui.info("Checking Postout system configuration...")
    ui.step_pause()

    try:
        available = system_profile_available()
    except NotificationError as exc:
        ui.fail(str(exc))
        return 3

    if not available:
        ui.warn("Email notifications are not configured")

        print()
        print(
            "  Have your SMTP server details, username and "
            "password/app password ready."
        )
        print()

        try:
            answer = input(
                "Configure email notifications now? [y/N]: "
            ).strip().lower()
        except EOFError:
            answer = ""

        if answer not in {"y", "yes"}:
            print()
            ui.warn("Notification configuration was not completed")
            return 3

        print()

        try:
            configure_system_profile()
        except NotificationError as exc:
            ui.fail(str(exc))
            return 3

        try:
            available = system_profile_available()
        except NotificationError as exc:
            ui.fail(str(exc))
            return 3

        if not available:
            ui.fail(
                f"Postout system profile "
                f"'{SYSTEM_PROFILE_NAME}' is still not available"
            )
            return 3

    print()

    ui.ok(
        f"Postout system profile "
        f"'{SYSTEM_PROFILE_NAME}' is available"
    )

    print()
    ui.info("Testing Postout notification delivery...")
    ui.step_pause()

    subject = "diskcapd notification test"

    body = (
        "diskcapd notification test\n"
        "\n"
        "This is a test notification from diskcapd.\n"
        "If you received this message, Postout delivery is working.\n"
    )

    try:
        result = send_notification(
            recipient=recipient,
            subject=subject,
            body=body,
        )
    except NotificationError as exc:
        ui.fail(str(exc))
        return 3

    print()
    ui.kv("Profile", f"{SYSTEM_PROFILE_NAME} (system)")
    ui.kv("Recipient", result.recipient)
    print()

    ui.ok("Test notification delivered successfully")
    print()

    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diskcapd",
        description=(
            "Monitor local block-backed filesystems for capacity, mount "
            "availability, and filesystem identity changes."
        ),
        epilog="""Examples:
  diskcapd discover
  sudo diskcapd setup
  sudo diskcapd status
  sudo diskcapd check --quiet
  sudo diskcapd test-notification --to admin@example.com

For full documentation, see diskcapd(1).""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
    )

    subparsers.add_parser(
        "discover",
        help="List eligible local filesystems",
        description=(
            "List mounted writable local block-backed filesystems that are "
            "eligible for monitoring."
        ),
    )

    setup_parser = subparsers.add_parser(
        "setup",
        help="Configure filesystems, notifications, and monitoring",
        description=(
            "Configure filesystems, notifications, and optional "
            "unattended monitoring."
        ),
    )

    setup_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Configuration file path (default: {DEFAULT_CONFIG_PATH})",
    )

    status_parser = subparsers.add_parser(
        "status",
        help="Show current monitoring status",
        description=(
            "Show the current status of configured monitored filesystems."
        ),
    )

    status_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Configuration file path (default: {DEFAULT_CONFIG_PATH})",
    )

    check_parser = subparsers.add_parser(
        "check",
        help="Check filesystems and process monitoring state",
        description=(
            "Check configured filesystems, evaluate monitoring state, and "
            "send notifications for alerts, reminders, and recoveries."
        ),
    )

    check_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Configuration file path (default: {DEFAULT_CONFIG_PATH})",
    )

    check_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help=f"State file path (default: {DEFAULT_STATE_PATH})",
    )

    check_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress steady-state output; show transitions and errors only",
    )

    notification_parser = subparsers.add_parser(
        "test-notification",
        help="Send a test notification through Postout",
        description=(
            "Send a test notification through the configured system "
            "Postout profile."
        ),
    )

    notification_parser.add_argument(
        "--to",
        required=True,
        dest="recipient",
        help="Notification recipient email address",
    )

    return parser


def _entrypoint(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "discover":
        return run_discover()

    if args.command == "setup":
        return run_setup(args.config)

    if args.command == "status":
        return run_status(args.config)

    if args.command == "check":
        return run_check(
            args.config,
            args.state,
            quiet=args.quiet,
        )

    if args.command == "test-notification":
        return run_test_notification(
            args.recipient,
        )

    parser.error(f"Unknown command: {args.command}")
    return 2

def entrypoint(argv: Optional[list[str]] = None) -> int:
    """Run the CLI and handle interactive cancellation cleanly."""

    try:
        return _entrypoint(argv)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        ui.cancelled()
        return 130

