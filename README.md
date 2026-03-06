# FolderSync — macOS Menu Bar App

A macOS menu bar wrapper around [rclone](https://rclone.org/) that automatically syncs your Google Drive to a NAS (or any local/network folder) on a schedule. It provides a native UI for what would otherwise be a cron job + CLI command. Built with Python, [rumps](https://github.com/jaredks/rumps), and PyInstaller.

---

## Features

- **Live menu bar icon** — ☁️ idle / 🔄 syncing / ⚠️ error / ⏸️ paused
- **Real-time sync progress** — current file, data transferred, speed, ETA, files remaining
- **Configurable sync interval** — default 5 minutes, changeable from the menu
- **Interactive folder picker** — native macOS file browser for selecting source and destination
- **Sync history** — last 20 sync results with outcome, data size, file count, and duration
- **Pause / Resume** without quitting
- **Sync Now** for instant manual sync
- **In-app configuration** — set source, destination, and interval from the menu
- **Clean uninstall** — removes app, config, history, and logs; never touches your data folders
- **Logs** viewable via Console.app

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Menu Bar (rumps)                  │
│  app.py — FolderSyncApp                               │
│  ┌───────────┐ ┌──────────┐ ┌────────────────────┐  │
│  │  Status   │ │ Progress │ │ Recent Syncs       │  │
│  │  ☁️ / 🔄  │ │ Data/ETA │ │ ✅ Mar 05, 10:00   │  │
│  │  / ⚠️ / ⏸️│ │ Speed    │ │ ❌ Mar 05, 09:55   │  │
│  │           │ │ Files    │ │ ...                │  │
│  └───────────┘ └──────────┘ └────────────────────┘  │
│                       │                              │
│              on_progress callback                    │
│                       │                              │
│  ┌────────────────────▼─────────────────────────┐   │
│  │  sync.py — Core sync engine                  │   │
│  │                                              │   │
│  │  run_sync_live()                             │   │
│  │    ├─ validate_paths()                       │   │
│  │    ├─ build_rclone_command()                 │   │
│  │    ├─ subprocess.Popen (streams stderr)      │   │
│  │    ├─ parse_stats_line() ──→ SyncProgress    │   │
│  │    └─ returns SyncResult                     │   │
│  │                                              │   │
│  │  Config: load_config() / save_config()       │   │
│  │  History: add_history_entry() / load_history()│  │
│  │  Cleanup: cleanup_app_data() / uninstall_app()│  │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
  ┌──────────────┐             ┌──────────────────┐
  │   rclone     │             │  ~/.foldersync     │
  │   sync       │             │  .json           │
  │              │             │  -history.json   │
  │  Google Drive│             │  ~/foldersync      │
  │  ──────────► │             │  .log            │
  │  NAS         │             └──────────────────┘
  └──────────────┘
```

### How it works

1. **Startup** — `app.py` creates a `rumps.App` menu bar icon, loads config from `~/.foldersync.json`, and starts a background sync loop thread.

2. **Sync loop** — A daemon thread runs `run_sync_live()` immediately, then sleeps for `interval_minutes` before repeating. The loop respects a `threading.Event` for pause/cancel.

3. **Sync execution** — `run_sync_live()` in `sync.py`:
   - Validates that source (Google Drive) and destination (NAS) paths are mounted
   - Launches `rclone sync` via `subprocess.Popen` with `--stats=1s --stats-one-line --progress`
   - Streams stderr line-by-line, parsing real-time stats with regex into a `SyncProgress` dataclass
   - Calls `on_progress` callback to update the menu bar every second
   - Returns a `SyncResult` with outcome, bytes transferred, file count, and duration

4. **History** — Each sync result is appended to `~/.foldersync-history.json` (last 20 entries). Viewable in the **Recent Syncs** submenu.

5. **Configuration** — Stored in `~/.foldersync.json`. Editable via the **Configure** submenu. Source and destination use a native macOS folder picker (NSOpenPanel).

### File structure

```
gdrive-nas-sync/
├── app.py              # Menu bar UI (rumps), sync loop, user interactions
├── sync.py             # Core logic: config, sync, progress parsing, history
├── tests/
│   ├── test_config.py  # Config load/save/merge tests
│   ├── test_sync.py    # Path validation, rclone command, stats parsing tests
│   └── test_history.py # History persistence and cleanup tests
├── pyproject.toml      # Project config (uv, ruff, pytest)
├── Makefile            # Dev commands: install, lint, fmt, test, build, deploy
├── build.sh            # Build .app + .dmg, optional install
├── FolderSync.spec       # PyInstaller spec for macOS .app bundle
├── .python-version     # Python 3.14
└── README.md
```

---

## Requirements

- macOS 13+ (Ventura or later)
- [Homebrew](https://brew.sh)
- Google Drive for Desktop running (mounts at `/Volumes/Google Drive`)
- NAS mounted via SMB (Finder → Go → Connect to Server → `smb://NAS_IP/share`)

---

## Quick start

### Build the app

```bash
git clone <repo-url> && cd gdrive-nas-sync
chmod +x build.sh
./build.sh
```

This installs `rclone`, `uv`, Python dependencies, builds `FolderSync.app` and a `.dmg` installer.

### Install and launch

```bash
./build.sh --install
```

Or use the Makefile:

```bash
make deploy    # build + install + launch
```

---

## Development

```bash
make install   # install dependencies with uv
make test      # run pytest
make lint      # ruff check + format check
make fmt       # auto-fix lint + format
make build     # build .app + .dmg (no install)
make clean     # remove build artifacts
```

### Tech stack

| Tool | Purpose |
|------|---------|
| [uv](https://docs.astral.sh/uv/) | Package/project management |
| [ruff](https://docs.astral.sh/ruff/) | Linting and formatting |
| [pytest](https://docs.pytest.org/) | Testing |
| [rumps](https://github.com/jaredks/rumps) | macOS menu bar framework |
| [pyobjc](https://pyobjc.readthedocs.io/) | Native macOS folder picker (NSOpenPanel) |
| [rclone](https://rclone.org/) | File sync engine |
| [PyInstaller](https://pyinstaller.org/) | Packaging into `.app` |

---

## Configuration

Click the menu bar icon → **Configure** to set:

| Setting | Description | Default |
|---------|-------------|---------|
| **Source** | Path to your Google Drive mount (opens folder picker) | `/Volumes/Google Drive/My Drive` |
| **Destination** | Path to your NAS mount (opens folder picker) | `/Volumes/NAS` |
| **Interval** | Minutes between syncs | `5` |

Config is stored at `~/.foldersync.json`.

---

## Menu bar reference

| Menu item | Description |
|-----------|-------------|
| **Status** | Current state (Idle / Syncing / Error / Paused) |
| **Last sync** | Timestamp of the last successful sync |
| **Progress** | Live submenu: data, speed, files, ETA, current file |
| **Sync Now** | Trigger an immediate sync |
| **Pause / Resume** | Toggle the sync loop |
| **Recent Syncs** | Last 10 sync results with outcome and stats |
| **Configure** | Set source, destination, interval |
| **View Log** | Open `~/foldersync.log` in Console.app |
| **Uninstall...** | Remove app + all data files (Google Drive and NAS untouched) |
| **Quit** | Stop syncing and exit |

---

## Auto-start on login

1. Open **System Settings → General → Login Items**
2. Click **+** and add `/Applications/FolderSync.app`

---

## Data files

| File | Purpose |
|------|---------|
| `~/.foldersync.json` | User configuration |
| `~/.foldersync-history.json` | Last 20 sync results |
| `~/foldersync.log` | rclone sync log |

All removed on uninstall. Your Google Drive and NAS folders are **never** modified or deleted by this app.

To fully uninstall (app + all data files), run:

```bash
make uninstall
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| ⚠️ "Google Drive not mounted" | Make sure Google Drive for Desktop is running |
| ⚠️ "NAS not mounted" | Reconnect via Finder → Go → Connect to Server |
| ⚠️ "rclone not found" | Run `brew install rclone` in Terminal |
| App doesn't appear | Check `/Applications/FolderSync.app` exists, try opening manually |
| Sync is slow | Check network speed; adjust `--transfers` and `--checkers` in `sync.py` |
