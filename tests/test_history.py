import os
import plistlib
from unittest.mock import patch

from sync import (
    MAX_HISTORY,
    SyncResult,
    add_history_entry,
    cleanup_app_data,
    install_launchd_plist,
    is_launchd_installed,
    load_history,
    save_history,
    uninstall_launchd_plist,
)


def test_load_history_returns_empty_when_no_file(tmp_path):
    history_file = str(tmp_path / 'nonexistent.json')
    assert load_history(history_file) == []


def test_save_and_load_roundtrip(tmp_path):
    history_file = str(tmp_path / 'history.json')
    entries = [
        {
            'timestamp': 'Mar 01, 10:00',
            'success': True,
            'error': None,
            'bytes_transferred': '1.0 GiB',
            'files_transferred': 5,
            'duration_seconds': 60,
        },
    ]
    save_history(entries, history_file)
    loaded = load_history(history_file)
    assert loaded == entries


def test_save_history_truncates_to_max(tmp_path):
    history_file = str(tmp_path / 'history.json')
    entries = [{'timestamp': f'entry_{i}', 'success': True} for i in range(MAX_HISTORY + 10)]
    save_history(entries, history_file)
    loaded = load_history(history_file)
    assert len(loaded) == MAX_HISTORY
    assert loaded[0]['timestamp'] == f'entry_{10}'


def test_add_history_entry_appends(tmp_path):
    history_file = str(tmp_path / 'history.json')
    result = SyncResult(timestamp='Mar 01, 10:00', success=True, bytes_transferred='2.0 GiB', files_transferred=10, duration_seconds=120)
    add_history_entry(result, history_file)

    history = load_history(history_file)
    assert len(history) == 1
    assert history[0]['success'] is True
    assert history[0]['bytes_transferred'] == '2.0 GiB'
    assert history[0]['files_transferred'] == 10
    assert history[0]['duration_seconds'] == 120


def test_add_history_entry_failure(tmp_path):
    history_file = str(tmp_path / 'history.json')
    result = SyncResult(timestamp='Mar 01, 11:00', success=False, error='NAS not mounted')
    add_history_entry(result, history_file)

    history = load_history(history_file)
    assert len(history) == 1
    assert history[0]['success'] is False
    assert history[0]['error'] == 'NAS not mounted'


def test_add_multiple_entries_preserves_order(tmp_path):
    history_file = str(tmp_path / 'history.json')
    for i in range(3):
        result = SyncResult(timestamp=f'entry_{i}', success=True, files_transferred=i)
        add_history_entry(result, history_file)

    history = load_history(history_file)
    assert len(history) == 3
    assert history[0]['timestamp'] == 'entry_0'
    assert history[2]['timestamp'] == 'entry_2'


class TestCleanupAppData:
    def test_removes_existing_files(self, tmp_path):
        config = tmp_path / 'config.json'
        history = tmp_path / 'history.json'
        log = tmp_path / 'sync.log'
        config.write_text('{}')
        history.write_text('[]')
        log.write_text('log data')

        with (
            patch('sync.CONFIG_FILE', str(config)),
            patch('sync.HISTORY_FILE', str(history)),
            patch('sync.LOG_FILE', str(log)),
        ):
            removed = cleanup_app_data()

        assert len(removed) == 3
        assert not config.exists()
        assert not history.exists()
        assert not log.exists()

    def test_skips_missing_files(self, tmp_path):
        config = tmp_path / 'config.json'
        config.write_text('{}')

        with (
            patch('sync.CONFIG_FILE', str(config)),
            patch('sync.HISTORY_FILE', str(tmp_path / 'nonexistent.json')),
            patch('sync.LOG_FILE', str(tmp_path / 'nonexistent.log')),
        ):
            removed = cleanup_app_data()

        assert len(removed) == 1
        assert str(config) in removed

    def test_does_not_touch_source_or_destination(self, tmp_path):
        source = tmp_path / 'gdrive'
        dest = tmp_path / 'nas'
        source.mkdir()
        dest.mkdir()
        (source / 'file.txt').write_text('important')
        (dest / 'backup.txt').write_text('important')

        with (
            patch('sync.CONFIG_FILE', str(tmp_path / 'c.json')),
            patch('sync.HISTORY_FILE', str(tmp_path / 'h.json')),
            patch('sync.LOG_FILE', str(tmp_path / 'l.log')),
        ):
            cleanup_app_data()

        assert source.exists()
        assert dest.exists()
        assert (source / 'file.txt').read_text() == 'important'
        assert (dest / 'backup.txt').read_text() == 'important'


class TestLaunchdPlist:
    def test_install_creates_plist(self, tmp_path):
        app_path = tmp_path / 'UNasSync.app' / 'Contents' / 'MacOS'
        app_path.mkdir(parents=True)
        plist_path = str(tmp_path / 'com.user.unassync.plist')

        with (
            patch('sync.APP_PATH', str(tmp_path / 'UNasSync.app')),
            patch('sync.LAUNCHD_PLIST', plist_path),
            patch('sync.subprocess.run'),
        ):
            result = install_launchd_plist()

        assert result is True
        assert os.path.exists(plist_path)
        with open(plist_path, 'rb') as f:
            plist = plistlib.load(f)
        assert plist['Label'] == 'com.user.unassync'
        assert plist['RunAtLoad'] is True

    def test_install_fails_when_app_missing(self, tmp_path):
        plist_path = str(tmp_path / 'com.user.unassync.plist')

        with (
            patch('sync.APP_PATH', str(tmp_path / 'NonExistent.app')),
            patch('sync.LAUNCHD_PLIST', plist_path),
        ):
            result = install_launchd_plist()

        assert result is False
        assert not os.path.exists(plist_path)

    def test_uninstall_removes_plist(self, tmp_path):
        plist_path = tmp_path / 'com.user.unassync.plist'
        plist_path.write_text('fake')

        with (
            patch('sync.LAUNCHD_PLIST', str(plist_path)),
            patch('sync.subprocess.run'),
        ):
            result = uninstall_launchd_plist()

        assert result is True
        assert not plist_path.exists()

    def test_uninstall_returns_false_when_no_plist(self, tmp_path):
        with patch('sync.LAUNCHD_PLIST', str(tmp_path / 'nonexistent.plist')):
            result = uninstall_launchd_plist()
        assert result is False

    def test_is_launchd_installed(self, tmp_path):
        plist_path = tmp_path / 'com.user.unassync.plist'

        with patch('sync.LAUNCHD_PLIST', str(plist_path)):
            assert is_launchd_installed() is False

        plist_path.write_text('fake')
        with patch('sync.LAUNCHD_PLIST', str(plist_path)):
            assert is_launchd_installed() is True
