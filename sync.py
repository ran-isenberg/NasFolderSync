import json
import os
import plistlib
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

CONFIG_FILE = os.path.expanduser('~/.unassync.json')
HISTORY_FILE = os.path.expanduser('~/.unassync-history.json')
LOG_FILE = os.path.expanduser('~/unassync.log')
APP_PATH = '/Applications/NasFolderSync.app'
MAX_HISTORY = 20

LAUNCHD_LABEL = 'com.user.unassync'
LAUNCHD_PLIST = os.path.expanduser(f'~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist')

DEFAULT_CONFIG = {
    'source': '/Volumes/Google Drive/My Drive',
    'destination': '/Volumes/NAS',
    'interval_minutes': 5,
    'enabled': True,
    'use_checksum': False,
}

# rclone --stats-one-line output patterns
# "Transferred:   1.234 GiB / 5.678 GiB, 22%, 10.5 MiB/s, ETA 5m30s"
_RE_TRANSFER_STATS = re.compile(
    r'Transferred:\s+'
    r'(?P<transferred>[\d.]+ \S+)\s*/\s*(?P<total>[\d.]+ \S+),\s*'
    r'(?P<percent>\d+)%'
    r'(?:,\s*(?P<speed>[\d.]+ \S+/s))?'
    r'(?:,\s*ETA\s*(?P<eta>\S+))?'
)

# "Transferred:   10 / 50, 20%"
_RE_FILE_STATS = re.compile(r'Transferred:\s+(?P<done>\d+)\s*/\s*(?P<total>\d+),\s*(?P<percent>\d+)%')

# "Transferring:\n *  filename.ext: 22% /1.2Mi, 500Ki/s, 1s"
_RE_CURRENT_FILE = re.compile(r'^\s*\*\s+(?P<name>.+?):\s*(?P<detail>.+)$')


@dataclass
class SyncProgress:
    bytes_transferred: str = ''
    bytes_total: str = ''
    percent: int = 0
    speed: str = ''
    eta: str = ''
    files_done: int = 0
    files_total: int = 0
    current_file: str = ''
    current_file_detail: str = ''


@dataclass
class SyncResult:
    timestamp: str = ''
    success: bool = False
    error: str | None = None
    bytes_transferred: str = ''
    files_transferred: int = 0
    duration_seconds: int = 0


def parse_stats_line(line: str, progress: SyncProgress) -> SyncProgress:
    """Parse a single line of rclone --stats output and update progress in-place."""
    # Try data transfer stats first (more specific pattern)
    m = _RE_TRANSFER_STATS.search(line)
    if m:
        progress.bytes_transferred = m.group('transferred')
        progress.bytes_total = m.group('total')
        progress.percent = int(m.group('percent'))
        if m.group('speed'):
            progress.speed = m.group('speed')
        if m.group('eta'):
            progress.eta = m.group('eta')
        return progress

    # Try file count stats
    m = _RE_FILE_STATS.search(line)
    if m:
        progress.files_done = int(m.group('done'))
        progress.files_total = int(m.group('total'))
        return progress

    # Try current file
    m = _RE_CURRENT_FILE.search(line)
    if m:
        progress.current_file = m.group('name')
        progress.current_file_detail = m.group('detail')
        return progress

    return progress


def load_config(config_file: str = CONFIG_FILE) -> dict:
    if os.path.exists(config_file):
        with open(config_file) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()


def save_config(config: dict, config_file: str = CONFIG_FILE) -> None:
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)


def install_launchd_plist() -> bool:
    """Install a launchd plist so the app starts automatically on login. Returns True on success."""
    if not os.path.isdir(APP_PATH):
        return False

    plist = {
        'Label': LAUNCHD_LABEL,
        'ProgramArguments': [os.path.join(APP_PATH, 'Contents', 'MacOS', 'NasFolderSync')],
        'RunAtLoad': True,
        'KeepAlive': False,
    }

    os.makedirs(os.path.dirname(LAUNCHD_PLIST), exist_ok=True)
    with open(LAUNCHD_PLIST, 'wb') as f:
        plistlib.dump(plist, f)

    subprocess.run(['launchctl', 'unload', LAUNCHD_PLIST], capture_output=True, check=False)
    subprocess.run(['launchctl', 'load', LAUNCHD_PLIST], capture_output=True, check=False)
    return True


def uninstall_launchd_plist() -> bool:
    """Remove the launchd plist so the app no longer starts on login. Returns True if removed."""
    if not os.path.exists(LAUNCHD_PLIST):
        return False
    subprocess.run(['launchctl', 'unload', LAUNCHD_PLIST], capture_output=True, check=False)
    os.remove(LAUNCHD_PLIST)
    return True


def is_launchd_installed() -> bool:
    """Check if the launchd plist is currently installed."""
    return os.path.exists(LAUNCHD_PLIST)


def cleanup_app_data() -> list[str]:
    """Remove all app data files (config, history, log). Returns list of removed paths.
    Does NOT touch Google Drive or NAS folders.
    """
    removed = []
    for path in [CONFIG_FILE, HISTORY_FILE, LOG_FILE]:
        if os.path.exists(path):
            os.remove(path)
            removed.append(path)
    return removed


def uninstall_app() -> list[str]:
    """Remove the app from /Applications and clean up all app data.
    Does NOT touch Google Drive or NAS folders.
    """
    removed = cleanup_app_data()
    if uninstall_launchd_plist():
        removed.append(LAUNCHD_PLIST)
    if os.path.isdir(APP_PATH):
        shutil.rmtree(APP_PATH)
        removed.append(APP_PATH)
    return removed


def load_history(history_file: str = HISTORY_FILE) -> list[dict]:
    if os.path.exists(history_file):
        with open(history_file) as f:
            return json.load(f)
    return []


def save_history(history: list[dict], history_file: str = HISTORY_FILE) -> None:
    with open(history_file, 'w') as f:
        json.dump(history[-MAX_HISTORY:], f, indent=2)


def add_history_entry(result: SyncResult, history_file: str = HISTORY_FILE) -> None:
    history = load_history(history_file)
    history.append(
        {
            'timestamp': result.timestamp,
            'success': result.success,
            'error': result.error,
            'bytes_transferred': result.bytes_transferred,
            'files_transferred': result.files_transferred,
            'duration_seconds': result.duration_seconds,
        }
    )
    save_history(history, history_file)


def validate_paths(source: str, destination: str) -> str | None:
    """Return an error message if paths are invalid, None if OK."""
    if not os.path.isdir(source):
        return 'Google Drive not mounted'
    if not os.path.isdir(destination):
        return 'NAS not mounted'
    return None


def build_rclone_command(source: str, destination: str, log_file: str | None = None, use_checksum: bool = False) -> list[str]:
    if log_file is None:
        log_file = os.path.expanduser('~/unassync.log')
    cmd = [
        'rclone',
        'sync',
        source,
        destination,
        '--transfers=4',
        '--checkers=8',
        f'--log-file={log_file}',
        '--log-level=INFO',
        '--stats=1s',
        '--stats-one-line',
        '--progress',
    ]
    if use_checksum:
        cmd.append('--checksum')
    return cmd


def run_sync(source: str, destination: str, log_file: str | None = None, use_checksum: bool = False) -> tuple[bool, str | None, str | None]:
    """Run rclone sync (blocking, no progress). Returns (success, error_message, timestamp)."""
    path_error = validate_paths(source, destination)
    if path_error:
        return False, path_error, None

    cmd = build_rclone_command(source, destination, log_file, use_checksum=use_checksum)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
        if result.returncode == 0:
            timestamp = datetime.now().strftime('%b %d, %H:%M')
            return True, None, timestamp
        else:
            error = result.stderr.strip().split('\n')[-1][:80] if result.stderr else 'rclone error'
            return False, error, None
    except FileNotFoundError:
        return False, 'rclone not found — run: brew install rclone', None
    except subprocess.TimeoutExpired:
        return False, 'Sync timed out', None
    except Exception as e:
        return False, str(e)[:80], None


def run_sync_live(
    source: str,
    destination: str,
    on_progress: Callable[[SyncProgress], None] | None = None,
    stop_event=None,
    log_file: str | None = None,
    use_checksum: bool = False,
) -> SyncResult:
    """Run rclone sync with real-time progress updates via callback."""
    path_error = validate_paths(source, destination)
    if path_error:
        return SyncResult(
            timestamp=datetime.now().strftime('%b %d, %H:%M'),
            success=False,
            error=path_error,
        )

    cmd = build_rclone_command(source, destination, log_file, use_checksum=use_checksum)
    progress = SyncProgress()
    start_time = datetime.now()

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Read stderr for progress (rclone writes stats to stderr)
        while True:
            if stop_event and stop_event.is_set():
                proc.terminate()
                proc.wait(timeout=5)
                return SyncResult(
                    timestamp=datetime.now().strftime('%b %d, %H:%M'),
                    success=False,
                    error='Sync cancelled',
                    duration_seconds=int((datetime.now() - start_time).total_seconds()),
                )

            line = proc.stderr.readline()
            if not line and proc.poll() is not None:
                break
            if line:
                parse_stats_line(line.strip(), progress)
                if on_progress:
                    on_progress(progress)

        duration = int((datetime.now() - start_time).total_seconds())

        if proc.returncode == 0:
            return SyncResult(
                timestamp=datetime.now().strftime('%b %d, %H:%M'),
                success=True,
                bytes_transferred=progress.bytes_transferred,
                files_transferred=progress.files_done,
                duration_seconds=duration,
            )
        else:
            remaining_stderr = proc.stderr.read()
            last_line = remaining_stderr.strip().split('\n')[-1][:80] if remaining_stderr.strip() else 'rclone error'
            return SyncResult(
                timestamp=datetime.now().strftime('%b %d, %H:%M'),
                success=False,
                error=last_line,
                bytes_transferred=progress.bytes_transferred,
                files_transferred=progress.files_done,
                duration_seconds=duration,
            )
    except FileNotFoundError:
        return SyncResult(
            timestamp=datetime.now().strftime('%b %d, %H:%M'),
            success=False,
            error='rclone not found — run: brew install rclone',
        )
    except Exception as e:
        return SyncResult(
            timestamp=datetime.now().strftime('%b %d, %H:%M'),
            success=False,
            error=str(e)[:80],
            duration_seconds=int((datetime.now() - start_time).total_seconds()),
        )
