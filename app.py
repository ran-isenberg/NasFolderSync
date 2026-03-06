import os
import signal
import subprocess
import threading
import time

import objc
import rumps
from AppKit import NSURL, NSOpenPanel

from sync import (
    SyncProgress,
    add_history_entry,
    install_launchd_plist,
    is_launchd_installed,
    load_config,
    load_history,
    run_sync_live,
    save_config,
    uninstall_app,
    uninstall_launchd_plist,
)


def _pick_folder(title: str, start_path: str | None = None) -> str | None:
    """Open a native macOS folder picker dialog. Returns the chosen path or None if cancelled."""
    panel = NSOpenPanel.openPanel()
    panel.setTitle_(title)
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setCanCreateDirectories_(False)

    if start_path and os.path.isdir(start_path):
        panel.setDirectoryURL_(NSURL.fileURLWithPath_(start_path))

    if panel.runModal() == objc.YES:
        return str(panel.URL().path())
    return None


class UNasSyncApp(rumps.App):
    def __init__(self):
        super().__init__('UNasSync', quit_button=None)
        self.config = load_config()

        self.status = 'idle'
        self.last_sync = None
        self.last_error = None
        self.sync_thread = None
        self.stop_event = threading.Event()
        self.progress = SyncProgress()

        # Menu items
        self.status_item = rumps.MenuItem('Status: Idle')
        self.status_item.set_callback(None)

        self.last_sync_item = rumps.MenuItem('Last sync: Never')
        self.last_sync_item.set_callback(None)

        # Progress submenu (visible during sync)
        self.progress_menu = rumps.MenuItem('Progress')
        self.progress_data_item = rumps.MenuItem('Data: —')
        self.progress_data_item.set_callback(None)
        self.progress_speed_item = rumps.MenuItem('Speed: —')
        self.progress_speed_item.set_callback(None)
        self.progress_files_item = rumps.MenuItem('Files: —')
        self.progress_files_item.set_callback(None)
        self.progress_eta_item = rumps.MenuItem('ETA: —')
        self.progress_eta_item.set_callback(None)
        self.progress_current_item = rumps.MenuItem('File: —')
        self.progress_current_item.set_callback(None)
        self.progress_menu[self.progress_data_item.title] = self.progress_data_item
        self.progress_menu[self.progress_speed_item.title] = self.progress_speed_item
        self.progress_menu[self.progress_files_item.title] = self.progress_files_item
        self.progress_menu[self.progress_eta_item.title] = self.progress_eta_item
        self.progress_menu[self.progress_current_item.title] = self.progress_current_item

        self.toggle_item = rumps.MenuItem('Pause Sync', callback=self.toggle_sync)
        self.sync_now_item = rumps.MenuItem('Sync Now', callback=self.sync_now)

        # Recent syncs submenu
        self.history_menu = rumps.MenuItem('Recent Syncs')
        self._rebuild_history_menu()

        # Configure submenu
        self.configure_menu = rumps.MenuItem('Configure')
        self.source_item = rumps.MenuItem(f'Source: {self.config["source"]}', callback=self.set_source)
        self.dest_item = rumps.MenuItem(f'Destination: {self.config["destination"]}', callback=self.set_destination)
        self.interval_item = rumps.MenuItem(f'Interval: {self.config["interval_minutes"]} min', callback=self.set_interval)
        self.checksum_item = rumps.MenuItem('Use Checksum (slower, more accurate)', callback=self.toggle_checksum)
        self.checksum_item.state = self.config.get('use_checksum', False)
        self.autostart_item = rumps.MenuItem('Start on Login', callback=self.toggle_autostart)
        self.autostart_item.state = is_launchd_installed()
        self.configure_menu[self.source_item.title] = self.source_item
        self.configure_menu[self.dest_item.title] = self.dest_item
        self.configure_menu[self.interval_item.title] = self.interval_item
        self.configure_menu[self.checksum_item.title] = self.checksum_item
        self.configure_menu[self.autostart_item.title] = self.autostart_item

        self.open_log_item = rumps.MenuItem('View Log', callback=self.open_log)
        self.uninstall_item = rumps.MenuItem('Uninstall...', callback=self.uninstall)
        self.quit_item = rumps.MenuItem('Quit', callback=self.quit_app)

        self.menu = [
            self.status_item,
            self.last_sync_item,
            self.progress_menu,
            None,
            self.sync_now_item,
            self.toggle_item,
            None,
            self.history_menu,
            self.configure_menu,
            self.open_log_item,
            None,
            self.uninstall_item,
            self.quit_item,
        ]

        self.update_icon()
        self._install_signal_handlers()
        if self.config['enabled']:
            self.start_sync_loop()

    # ── Icon & menu updates ───────────────────────────────────────────

    def update_icon(self):
        icons = {
            'idle': '☁️',
            'syncing': '🔄',
            'error': '⚠️',
            'paused': '⏸️',
        }
        self.title = icons.get(self.status, '☁️')

    def update_menu(self):
        status_labels = {
            'idle': '✅  Status: Idle',
            'syncing': '🔄  Status: Syncing...',
            'error': f'❌  Status: Error — {self.last_error or "unknown"}',
            'paused': '⏸️  Status: Paused',
        }
        self.status_item.title = status_labels.get(self.status, 'Status: Unknown')

        if self.last_sync:
            self.last_sync_item.title = f'Last sync: {self.last_sync}'
        else:
            self.last_sync_item.title = 'Last sync: Never'

        if self.config['enabled']:
            self.toggle_item.title = 'Pause Sync'
        else:
            self.toggle_item.title = 'Resume Sync'

        self.update_icon()

    def _update_progress_menu(self, progress: SyncProgress):
        self.progress = progress
        if progress.bytes_total:
            self.progress_data_item.title = f'Data: {progress.bytes_transferred} / {progress.bytes_total} ({progress.percent}%)'
        self.progress_speed_item.title = f'Speed: {progress.speed or "—"}'
        if progress.files_total:
            files_left = progress.files_total - progress.files_done
            self.progress_files_item.title = f'Files: {progress.files_done} / {progress.files_total} ({files_left} left)'
        self.progress_eta_item.title = f'ETA: {progress.eta or "—"}'
        if progress.current_file:
            name = progress.current_file
            max_display = 40
            if len(name) > max_display:
                name = '...' + name[-(max_display - 3) :]
            self.progress_current_item.title = f'File: {name}'

    def _rebuild_history_menu(self):
        # Clear existing items
        for key in list(self.history_menu):
            del self.history_menu[key]

        history = load_history()
        if not history:
            empty_item = rumps.MenuItem('No syncs yet')
            empty_item.set_callback(None)
            self.history_menu[empty_item.title] = empty_item
            return

        for entry in reversed(history[-10:]):
            icon = '✅' if entry.get('success') else '❌'
            ts = entry.get('timestamp', '?')
            detail = entry.get('bytes_transferred', '') if entry.get('success') else (entry.get('error', 'unknown')[:30])
            files = entry.get('files_transferred', 0)
            duration = entry.get('duration_seconds', 0)

            if entry.get('success'):
                label = f'{icon} {ts} — {detail}, {files} files, {duration}s'
            else:
                label = f'{icon} {ts} — {detail}'

            item = rumps.MenuItem(label)
            item.set_callback(None)
            self.history_menu[label] = item

    def _reset_progress_menu(self):
        self.progress_data_item.title = 'Data: —'
        self.progress_speed_item.title = 'Speed: —'
        self.progress_files_item.title = 'Files: —'
        self.progress_eta_item.title = 'ETA: —'
        self.progress_current_item.title = 'File: —'

    # ── Sync loop ─────────────────────────────────────────────────────

    def start_sync_loop(self):
        self.stop_event.clear()
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()

    def _sync_loop(self):
        self._run_sync()
        while not self.stop_event.wait(timeout=self.config['interval_minutes'] * 60):
            if self.config['enabled']:
                self._run_sync()

    def _run_sync(self):
        self.status = 'syncing'
        self._reset_progress_menu()
        self.update_menu()

        result = run_sync_live(
            self.config['source'],
            self.config['destination'],
            on_progress=self._update_progress_menu,
            stop_event=self.stop_event,
            use_checksum=self.config.get('use_checksum', False),
        )

        if result.success:
            self.status = 'idle'
            self.last_error = None
            self.last_sync = result.timestamp
        else:
            self.status = 'error'
            self.last_error = result.error

        add_history_entry(result)
        self._rebuild_history_menu()
        self.update_menu()

    # ── Signal handling ────────────────────────────────────────────────

    def _install_signal_handlers(self):
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum, _frame):
        self.stop_event.set()
        rumps.quit_application()

    # ── Actions ───────────────────────────────────────────────────────

    def toggle_sync(self, _):
        self.config['enabled'] = not self.config['enabled']
        save_config(self.config)

        if self.config['enabled']:
            self.status = 'idle'
            self.start_sync_loop()
        else:
            self.stop_event.set()
            self.status = 'paused'

        self.update_menu()

    def sync_now(self, _):
        if self.status == 'syncing':
            return
        threading.Thread(target=self._run_sync, daemon=True).start()

    def _save_and_restart(self):
        save_config(self.config)
        self._update_config_menu()
        rumps.notification('UNasSync', 'Config saved', 'Settings updated. Restarting sync loop.', sound=False)
        self.stop_event.set()
        if self.config['enabled']:
            time.sleep(0.5)
            self.start_sync_loop()

    def _update_config_menu(self):
        self.source_item.title = f'Source: {self.config["source"]}'
        self.dest_item.title = f'Destination: {self.config["destination"]}'
        self.interval_item.title = f'Interval: {self.config["interval_minutes"]} min'

    def set_source(self, _):
        chosen = _pick_folder('Select Source Folder (Google Drive)', self.config['source'])
        if chosen:
            self.config['source'] = chosen
            self._save_and_restart()

    def set_destination(self, _):
        chosen = _pick_folder('Select Destination Folder (NAS)', self.config['destination'])
        if chosen:
            self.config['destination'] = chosen
            self._save_and_restart()

    def set_interval(self, _):
        w = rumps.Window(
            title='Sync Interval',
            message='Enter sync interval in minutes:',
            default_text=str(self.config['interval_minutes']),
            ok='Save',
            cancel='Cancel',
            dimensions=(420, 24),
        )
        response = w.run()
        if response.clicked and response.text.strip():
            try:
                minutes = int(response.text.strip())
                if minutes < 1:
                    rumps.notification('UNasSync', 'Error', 'Interval must be at least 1 minute.', sound=False)
                    return
                self.config['interval_minutes'] = minutes
                self._save_and_restart()
            except ValueError:
                rumps.notification('UNasSync', 'Error', 'Please enter a valid number.', sound=False)

    def toggle_checksum(self, _):
        self.config['use_checksum'] = not self.config.get('use_checksum', False)
        self.checksum_item.state = self.config['use_checksum']
        save_config(self.config)
        label = 'enabled' if self.config['use_checksum'] else 'disabled'
        rumps.notification('UNasSync', 'Checksum mode', f'Checksum comparison {label}.', sound=False)

    def toggle_autostart(self, _):
        if is_launchd_installed():
            uninstall_launchd_plist()
            self.autostart_item.state = False
            rumps.notification('UNasSync', 'Auto-start disabled', 'App will no longer start on login.', sound=False)
        elif install_launchd_plist():
            self.autostart_item.state = True
            rumps.notification('UNasSync', 'Auto-start enabled', 'App will start automatically on login.', sound=False)
        else:
            rumps.notification('UNasSync', 'Error', 'App not found in /Applications. Install first.', sound=False)

    def open_log(self, _):
        log = os.path.expanduser('~/unassync.log')
        if os.path.exists(log):
            subprocess.Popen(['open', '-a', 'Console', log])
        else:
            rumps.notification('UNasSync', 'No log yet', 'Run a sync first.', sound=False)

    def uninstall(self, _):
        response = rumps.alert(
            title='Uninstall UNasSync',
            message='This will remove the app, config, history, and log files.\nYour Google Drive and NAS folders will NOT be touched.',
            ok='Uninstall',
            cancel='Cancel',
        )
        if response == 1:
            self.stop_event.set()
            removed = uninstall_app()
            rumps.notification('UNasSync', 'Uninstalled', f'Removed {len(removed)} items. Goodbye!', sound=False)
            rumps.quit_application()

    def quit_app(self, _):
        self.stop_event.set()
        rumps.quit_application()


if __name__ == '__main__':
    UNasSyncApp().run()
