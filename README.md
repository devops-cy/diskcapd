# diskcapd

**Linux filesystem monitoring for disk usage, missing mounts, UUID changes, and email alerts.**

`diskcapd` is a small Linux monitoring tool for local block-backed filesystems.

It watches selected filesystems and reports when:

- disk usage reaches a configured threshold
- a configured mount disappears
- the filesystem UUID at a mountpoint changes
- a previous problem recovers

Notifications are delivered through [Postout](https://github.com/devops-cy/postout).

`diskcapd` is intended for simple, predictable server monitoring without requiring a large monitoring stack.

## Features

- Discovers writable local block-backed filesystems
- Supports regular disks, NVMe, Linux software RAID, LVM, device mapper, and dm-crypt
- Monitors filesystems by mountpoint and filesystem UUID
- Treats device paths such as `/dev/sda1` as diagnostic information only
- Detects missing mounts without falling back to a parent filesystem
- Configurable capacity threshold per filesystem
- ALERT notifications for new violations
- 24-hour REMINDER notifications for unresolved violations
- RECOVERY notifications when a filesystem returns to normal
- Aggregates multiple transitions into one notification per check
- HTML email notifications through Postout
- Optional unattended monitoring through systemd
- Python standard library only

Network filesystems, pseudo filesystems, swap, read-only mounts, tmpfs, and similar non-local filesystems are excluded from discovery.

## Requirements

`diskcapd` supports:

- Debian 11 or later
- Compatible Debian-based systems
- Python 3.9 or later
- Postout 1.0.0-5 or later
- systemd for unattended monitoring

The Debian package installs Postout automatically as a dependency.

## Installation

### Install from the DEVOPS CY APT repository

This is the recommended installation method.

Add the DEVOPS CY package repository:

```bash
sudo apt update
sudo apt install -y curl ca-certificates

sudo install -d -m 0755 /etc/apt/keyrings

curl -fsSL https://packages.devops.com.cy/devops-cy-archive-keyring.gpg \
  | sudo tee /etc/apt/keyrings/devops-cy-archive-keyring.gpg >/dev/null

echo "deb [signed-by=/etc/apt/keyrings/devops-cy-archive-keyring.gpg] https://packages.devops.com.cy/ devops-cy main" \
  | sudo tee /etc/apt/sources.list.d/devops-cy.list >/dev/null

sudo apt update
sudo apt install diskcapd
```

Postout is installed automatically if it is not already present.

Once the repository is configured, future `diskcapd` updates are delivered through the normal APT upgrade process.

The DEVOPS CY archive signing key fingerprint is:

```text
21ED 038C 18F1 DE46 8A36  6C3B 3742 2B90 4698 4C12
```

### Install from source

For development or source-based installation:

```bash
git clone https://github.com/devops-cy/diskcapd.git
cd diskcapd

python3 -m venv .venv
. .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install .
```

The `diskcapd` command will then be available inside the virtual environment.

Source installation does not install the packaged systemd service and timer.

## Quick start

Run the interactive setup:

```bash
sudo diskcapd setup
```

Setup will:

1. discover eligible local filesystems
2. let you choose which filesystems to monitor
3. ask for a capacity threshold for each filesystem
4. ask for the email notification recipient
5. configure the required Postout system profile if needed
6. send a test email
7. write the system configuration
8. optionally enable unattended monitoring

If Postout has not been configured yet, `diskcapd setup` opens the Postout SMTP configuration flow automatically.

Have the SMTP server details, username, and password or app password available during initial setup.

At the end of setup, `diskcapd` can enable its systemd timer:

```text
Enable unattended monitoring now? [Y/n]:
```

Accepting the default enables and starts unattended monitoring.

## Verify the installation

Check the installed version:

```bash
diskcapd --version
```

Show eligible local filesystems:

```bash
diskcapd discover
```

Show the configured monitoring status:

```bash
sudo diskcapd status
```

Run a check immediately:

```bash
sudo diskcapd check
```

For quiet scheduler-style operation:

```bash
sudo diskcapd check --quiet
```

A healthy check returns exit status `0`.

## Commands

### Discover filesystems

```bash
diskcapd discover
```

Lists writable local block-backed filesystems that are eligible for monitoring.

### Configure diskcapd

```bash
sudo diskcapd setup
```

Runs the interactive configuration workflow.

### Show monitoring status

```bash
sudo diskcapd status
```

Shows the configured filesystems, expected UUIDs, thresholds, and current state.

### Run a check

```bash
sudo diskcapd check
```

Checks all configured filesystems and processes any required notifications.

### Run a quiet check

```bash
sudo diskcapd check --quiet
```

Suppresses steady-state output and reports transitions and errors only.

This is the mode used by the packaged systemd service.

### Test notification delivery

```bash
sudo diskcapd test-notification --to admin@example.com
```

Sends a test notification through the configured Postout system profile.

### Help and manual

```bash
diskcapd --help
man diskcapd
```

## Monitoring model

`diskcapd` monitors explicitly configured mountpoints.

Each filesystem is identified by:

- its configured mountpoint
- its filesystem UUID

The current device path is diagnostic information only.

For example, a filesystem may appear as `/dev/sdf1` on one boot and `/dev/sdh1` on another. If the mountpoint and filesystem UUID are still correct, `diskcapd` treats it as the same filesystem.

If a configured mountpoint disappears, `diskcapd` reports the filesystem as missing. It does not silently inspect the parent filesystem instead.

If a filesystem is mounted at the expected mountpoint but the UUID does not match the configured UUID, `diskcapd` reports a filesystem identity violation.

Capacity thresholds are evaluated against the currently mounted filesystem.

## Notifications

`diskcapd` keeps persistent monitoring state so that repeated checks do not generate unnecessary email.

### ALERT

Sent when:

- a filesystem first enters a violation state
- an existing violation changes to a different violation

Examples include:

- capacity threshold reached
- configured mount missing
- unexpected filesystem UUID

### REMINDER

Sent when the same violation remains unresolved for 24 hours after the previous successful alert or reminder.

Checks remain silent between reminder intervals.

### RECOVERY

Sent when a previously violated filesystem returns to a healthy state.

If several filesystems change state during the same check, the transitions are aggregated into one email.

Required notification delivery happens before monitoring state is committed. If delivery fails, `diskcapd` does not silently advance the recorded notification state.

SMTP settings and credentials are managed by Postout. `diskcapd` does not store SMTP passwords in its own configuration.

## Unattended monitoring

The Debian package installs:

```text
diskcapd.service
diskcapd.timer
```

The timer is not enabled merely by installing the package.

It can be enabled during:

```bash
sudo diskcapd setup
```

or manually:

```bash
sudo systemctl enable --now diskcapd.timer
```

Check the timer:

```bash
systemctl status diskcapd.timer
systemctl list-timers diskcapd.timer --all
```

Inspect recent scheduled checks:

```bash
sudo journalctl \
  -u diskcapd.timer \
  -u diskcapd.service \
  --since "-30 min" \
  --no-pager
```

Disable unattended monitoring:

```bash
sudo systemctl disable --now diskcapd.timer
```

The packaged timer runs a check every five minutes.

## Exit status

`diskcapd` returns:

```text
0     Successful operation; for check, all monitored filesystems are healthy
1     One or more filesystem violations were detected
2     Configuration or operational error
3     Notification delivery failed
```

For the packaged systemd service, exit status `1` is treated as a successful service execution. A filesystem violation is a monitoring result, not a failure of the monitoring program.

## Files

System monitoring configuration:

```text
/etc/diskcapd/diskcapd.conf
```

Persistent monitoring state:

```text
/var/lib/diskcapd/state.json
```

Postout system profile configuration:

```text
/etc/postout/profiles.json
```

Installed systemd units:

```text
diskcapd.service
diskcapd.timer
```

## Privacy

Monitoring notifications use the system's short hostname.

`diskcapd` does not intentionally include FQDNs, IP addresses, domain names, operating-system details, or network configuration in notification messages.

## Development

Clone the repository:

```bash
git clone https://github.com/devops-cy/diskcapd.git
cd diskcapd
```

Run the test suite:

```bash
PYTHONPATH=src \
DISKCAPD_ANIMATION=0 \
python3 -m unittest discover -s tests -v
```

Build the Debian package:

```bash
dpkg-buildpackage -us -uc -b
```

The generated `.deb` is written to the parent directory.

## License

See [LICENSE](LICENSE).

## Maintainer

**DEVOPS CY**

- Email: info@devops.com.cy
- Website: https://devops.com.cy
