"""Terminal presentation helpers for diskcapd."""

from __future__ import annotations

import os
import sys
import time


UI_WIDTH = 60
UI_INNER_WIDTH = 58

ANIMATION = os.environ.get("DISKCAPD_ANIMATION", "1").lower() not in {
    "0",
    "false",
    "no",
}

STEP_DELAY = 0.25
SECTION_DELAY = 0.5


if sys.stdout.isatty():
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN = "\033[0;36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
else:
    RED = ""
    GREEN = ""
    YELLOW = ""
    CYAN = ""
    BOLD = ""
    DIM = ""
    RESET = ""


def step_pause() -> None:
    if ANIMATION:
        time.sleep(STEP_DELAY)


def section_pause() -> None:
    if ANIMATION:
        time.sleep(SECTION_DELAY)


def info(message: str) -> None:
    print(f"{CYAN}[INFO]{RESET} {message}")


def ok(message: str) -> None:
    print(f"{GREEN}[ OK ]{RESET} {message}")


def warn(message: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {message}")


def fail(message: str) -> None:
    print(f"{RED}[FAIL]{RESET} {message}", file=sys.stderr)


def box_top() -> None:
    print(f"{CYAN}╭{'─' * UI_INNER_WIDTH}╮{RESET}")


def box_bottom() -> None:
    print(f"{CYAN}╰{'─' * UI_INNER_WIDTH}╯{RESET}")


def box_center(text: str, style: str = "") -> None:
    text = text[:UI_INNER_WIDTH]
    padding = UI_INNER_WIDTH - len(text)
    left = padding // 2
    right = padding - left

    print(
        f"{CYAN}│{RESET}"
        f"{' ' * left}"
        f"{style}{text}{RESET}"
        f"{' ' * right}"
        f"{CYAN}│{RESET}"
    )


def header(version: str) -> None:
    print()
    box_top()
    box_center("DISK CAPACITY MONITOR", BOLD)
    box_center(f"diskcapd {version}", DIM)
    box_bottom()
    print()
    print(f"  {BOLD}diskcapd{RESET}")
    print(f"  {DIM}Local filesystem capacity monitor{RESET}")
    print()


def section(title: str) -> None:
    decorated = f" {title} "
    remaining = UI_WIDTH - len(decorated)

    if remaining < 4:
        print(f"\n{CYAN}{BOLD}{title}{RESET}\n")
        return

    left = remaining // 2
    right = remaining - left

    print()
    print(
        f"{CYAN}{'─' * left}{RESET}"
        f"{BOLD}{decorated}{RESET}"
        f"{CYAN}{'─' * right}{RESET}"
    )
    print()


def subheading(title: str) -> None:
    print(f"\n  {BOLD}{title}{RESET}\n")


def kv(key: str, value: str) -> None:
    print(f"  {key:<17} {value}")
