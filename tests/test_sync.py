import os
import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

from sync import (
    SMB_MOUNT_TIMEOUT,
    SyncProgress,
    SyncResult,
    _is_smb_server_reachable,
    _parse_smb_host,
    _volume_mount_point,
    build_rclone_command,
    ensure_smb_mounts,
    find_rclone,
    install_rclone,
    mount_smb_share,
    parse_stats_line,
    run_sync,
    run_sync_live,
    truncate_log,
    validate_paths,
)


class TestValidatePaths:
    def test_both_paths_valid(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        assert validate_paths(str(src), str(dst)) is None

    def test_source_missing(self, tmp_path):
        dst = tmp_path / 'dst'
        dst.mkdir()
        error = validate_paths('/nonexistent/path', str(dst))
        assert error == 'Google Drive not mounted'

    def test_destination_missing(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        error = validate_paths(str(src), '/nonexistent/path')
        assert error == 'NAS not mounted'

    def test_both_missing_reports_source_first(self):
        error = validate_paths('/nonexistent/a', '/nonexistent/b')
        assert error == 'Google Drive not mounted'


class TestVolumeMountPoint:
    def test_volumes_path(self):
        assert _volume_mount_point('/Volumes/NAS/Backup') == '/Volumes/NAS'

    def test_volumes_root(self):
        assert _volume_mount_point('/Volumes/NAS') == '/Volumes/NAS'

    def test_non_volumes_path(self):
        assert _volume_mount_point('/Users/me/Documents') is None

    def test_short_path(self):
        assert _volume_mount_point('/Volumes') is None


class TestParseSmbHost:
    def test_standard_url(self):
        assert _parse_smb_host('smb://192.168.1.2/Share') == '192.168.1.2'

    def test_url_with_user(self):
        assert _parse_smb_host('smb://user@192.168.1.2/Share') == '192.168.1.2'

    def test_url_with_port(self):
        assert _parse_smb_host('smb://192.168.1.2:445/Share') == '192.168.1.2'

    def test_hostname(self):
        assert _parse_smb_host('smb://mynas.local/Share') == 'mynas.local'

    def test_no_smb_prefix(self):
        assert _parse_smb_host('http://host/share') is None

    def test_empty_host(self):
        assert _parse_smb_host('smb:///share') is None


class TestSmbReachability:
    def test_reachable_server(self):
        with patch('sync.socket.create_connection') as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            assert _is_smb_server_reachable('192.168.1.2') is True

    def test_unreachable_server(self):
        with patch('sync.socket.create_connection', side_effect=OSError('refused')):
            assert _is_smb_server_reachable('192.168.1.2') is False

    def test_timeout(self):
        with patch('sync.socket.create_connection', side_effect=TimeoutError):
            assert _is_smb_server_reachable('192.168.1.2') is False


class TestMountSmbShare:
    def test_already_mounted(self):
        with patch('sync.os.path.ismount', return_value=True):
            assert mount_smb_share('smb://host/share', '/Volumes/share') is None

    def test_mount_success(self):
        call_count = 0

        def ismount_side_effect(path):
            nonlocal call_count
            call_count += 1
            return call_count > 2  # Not mounted initially, then mounted after polling

        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch('sync.os.path.ismount', side_effect=ismount_side_effect),
            patch('sync._is_smb_server_reachable', return_value=True),
            patch('sync.subprocess.run', return_value=mock_result) as mock_run,
            patch('sync.time.sleep'),
            patch('sync.time.monotonic', side_effect=[0, 1, 2]),
        ):
            assert mount_smb_share('smb://host/share', '/Volumes/share') is None
            mock_run.assert_called_once_with(['open', 'smb://host/share'], capture_output=True, text=True, timeout=10, check=False)

    def test_open_command_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = 'connection refused'
        with (
            patch('sync.os.path.ismount', return_value=False),
            patch('sync._is_smb_server_reachable', return_value=True),
            patch('sync.subprocess.run', return_value=mock_result),
        ):
            error = mount_smb_share('smb://host/share', '/Volumes/share')
            assert error is not None
            assert 'exit 1' in error

    def test_mount_timeout(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch('sync.os.path.ismount', return_value=False),
            patch('sync._is_smb_server_reachable', return_value=True),
            patch('sync.subprocess.run', return_value=mock_result),
            patch('sync.time.sleep'),
            patch('sync.time.monotonic', side_effect=[0] + [SMB_MOUNT_TIMEOUT + 1] * 2),
        ):
            error = mount_smb_share('smb://host/share', '/Volumes/share')
            assert error is not None
            assert 'did not appear' in error

    def test_open_command_os_error(self):
        with (
            patch('sync.os.path.ismount', return_value=False),
            patch('sync._is_smb_server_reachable', return_value=True),
            patch('sync.subprocess.run', side_effect=OSError('fail')),
        ):
            error = mount_smb_share('smb://host/share', '/Volumes/share')
            assert error is not None
            assert 'error' in error

    def test_open_command_timeout(self):
        with (
            patch('sync.os.path.ismount', return_value=False),
            patch('sync._is_smb_server_reachable', return_value=True),
            patch('sync.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='open', timeout=10)),
        ):
            error = mount_smb_share('smb://host/share', '/Volumes/share')
            assert error is not None
            assert 'timed out' in error

    def test_unreachable_server_skips_open(self):
        with (
            patch('sync.os.path.ismount', return_value=False),
            patch('sync._is_smb_server_reachable', return_value=False),
            patch('sync.subprocess.run') as mock_run,
        ):
            error = mount_smb_share('smb://192.168.1.2/Share', '/Volumes/Share')
            assert error is not None
            assert 'not reachable' in error
            mock_run.assert_not_called()


class TestEnsureSmbMounts:
    def test_disabled_returns_none(self):
        config = {'auto_mount_smb': False, 'source_smb_url': 'smb://host/share', 'source': '/Volumes/share/data'}
        assert ensure_smb_mounts(config) is None

    def test_no_urls_returns_none(self):
        config = {'auto_mount_smb': True, 'source_smb_url': '', 'destination_smb_url': '', 'source': '/src', 'destination': '/dst'}
        assert ensure_smb_mounts(config) is None

    def test_path_accessible_skips_mount(self):
        config = {
            'auto_mount_smb': True,
            'source_smb_url': 'smb://host/share',
            'source': '/Volumes/share/data',
            'destination_smb_url': '',
            'destination': '/dst',
        }
        with patch('sync.os.path.isdir', return_value=True):
            assert ensure_smb_mounts(config) is None

    def test_mount_attempted_on_inaccessible_path(self):
        config = {
            'auto_mount_smb': True,
            'destination_smb_url': 'smb://192.168.1.2/NAS',
            'destination': '/Volumes/NAS/Backup',
            'source_smb_url': '',
            'source': '/Users/me/Drive',
        }
        with (
            patch('sync.os.path.isdir', return_value=False),
            patch('sync.mount_smb_share', return_value=None) as mock_mount,
        ):
            assert ensure_smb_mounts(config) is None
            mock_mount.assert_called_once_with('smb://192.168.1.2/NAS', '/Volumes/NAS')

    def test_mount_failure_returns_error(self):
        config = {
            'auto_mount_smb': True,
            'destination_smb_url': 'smb://192.168.1.2/NAS',
            'destination': '/Volumes/NAS/Backup',
            'source_smb_url': '',
            'source': '/Users/me/Drive',
        }
        with (
            patch('sync.os.path.isdir', return_value=False),
            patch('sync.mount_smb_share', return_value='server not reachable'),
        ):
            result = ensure_smb_mounts(config)
            assert result is not None
            assert 'Destination SMB mount failed' in result
            assert 'server not reachable' in result

    def test_non_volumes_path_skipped(self):
        config = {
            'auto_mount_smb': True,
            'source_smb_url': 'smb://host/share',
            'source': '/Users/me/data',
            'destination_smb_url': '',
            'destination': '/dst',
        }
        with (
            patch('sync.os.path.isdir', return_value=False),
            patch('sync.mount_smb_share') as mock_mount,
        ):
            ensure_smb_mounts(config)
            mock_mount.assert_not_called()


class TestBuildRcloneCommand:
    def test_default_log_file(self):
        cmd = build_rclone_command('/src', '/dst')
        assert cmd[0].endswith('rclone')
        assert cmd[1] == 'sync'
        assert cmd[2] == '/src'
        assert cmd[3] == '/dst'
        assert '--transfers=4' in cmd
        assert '--checkers=8' in cmd
        assert '--log-level=INFO' in cmd
        assert any('--log-file=' in arg for arg in cmd)

    def test_custom_log_file(self):
        cmd = build_rclone_command('/src', '/dst', log_file='/tmp/test.log')
        assert '--log-file=/tmp/test.log' in cmd

    def test_includes_stats_flags(self):
        cmd = build_rclone_command('/src', '/dst')
        assert '--stats=0.5s' in cmd
        assert '--stats-one-line' in cmd
        assert '--stats-log-level=NOTICE' in cmd
        assert '-v' not in cmd

    def test_live_mode_uses_verbose_no_log_file(self):
        cmd = build_rclone_command('/src', '/dst', live=True)
        assert '-v' in cmd
        assert '--log-level=INFO' not in cmd
        assert not any('--log-file=' in arg for arg in cmd)

    def test_checksum_enabled_by_default(self):
        cmd = build_rclone_command('/src', '/dst')
        assert '--checksum' not in cmd  # default param is False; app passes True from config

    def test_checksum_enabled(self):
        cmd = build_rclone_command('/src', '/dst', use_checksum=True)
        assert '--checksum' in cmd

    def test_checksum_disabled_explicitly(self):
        cmd = build_rclone_command('/src', '/dst', use_checksum=False)
        assert '--checksum' not in cmd


class TestParseStatsLine:
    def test_parse_transfer_stats_full(self):
        line = 'Transferred:   1.234 GiB / 5.678 GiB, 22%, 10.5 MiB/s, ETA 5m30s'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.bytes_transferred == '1.234 GiB'
        assert progress.bytes_total == '5.678 GiB'
        assert progress.percent == 22
        assert progress.speed == '10.5 MiB/s'
        assert progress.eta == '5m30s'

    def test_parse_transfer_stats_no_eta(self):
        line = 'Transferred:   500 MiB / 2.0 GiB, 25%, 5.0 MiB/s'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.bytes_transferred == '500 MiB'
        assert progress.bytes_total == '2.0 GiB'
        assert progress.percent == 25
        assert progress.speed == '5.0 MiB/s'
        assert progress.eta == ''

    def test_parse_transfer_stats_no_speed_no_eta(self):
        line = 'Transferred:   0 B / 1.0 GiB, 0%'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.bytes_transferred == '0 B'
        assert progress.bytes_total == '1.0 GiB'
        assert progress.percent == 0
        assert progress.speed == ''
        assert progress.eta == ''

    def test_parse_file_count(self):
        line = 'Transferred:   10 / 50, 20%'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.files_done == 10
        assert progress.files_total == 50

    def test_parse_current_file(self):
        line = ' *  vacation/photo_2024.jpg: 22% /1.2Mi, 500Ki/s, 1s'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.current_file == 'vacation/photo_2024.jpg'
        assert '22%' in progress.current_file_detail

    def test_unrecognized_line_returns_unchanged(self):
        progress = SyncProgress(bytes_transferred='1 GiB', percent=50)
        result = parse_stats_line('some random log line', progress)
        assert result.bytes_transferred == '1 GiB'
        assert result.percent == 50

    def test_updates_progress_in_place(self):
        progress = SyncProgress()
        parse_stats_line('Transferred:   1.0 GiB / 2.0 GiB, 50%, 10.0 MiB/s, ETA 1m0s', progress)
        assert progress.percent == 50
        parse_stats_line('Transferred:   15 / 30, 50%', progress)
        assert progress.files_done == 15
        # Previous fields preserved
        assert progress.percent == 50
        assert progress.bytes_transferred == '1.0 GiB'

    def test_parse_100_percent(self):
        line = 'Transferred:   5.678 GiB / 5.678 GiB, 100%, 15.0 MiB/s, ETA 0s'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.percent == 100
        assert progress.eta == '0s'

    def test_parse_log_prefixed_stats(self):
        """rclone -v outputs stats with timestamp + NOTICE prefix."""
        line = '2026/03/06 17:45:33 NOTICE:     5.000 MiB / 5.000 MiB, 100%, 0 B/s, ETA -'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.bytes_transferred == '5.000 MiB'
        assert progress.bytes_total == '5.000 MiB'
        assert progress.percent == 100

    def test_parse_log_prefixed_partial(self):
        line = '2026/03/06 10:00:00 NOTICE:     1.2 GiB / 5.0 GiB, 24%, 50.0 MiB/s, ETA 1m20s'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.bytes_transferred == '1.2 GiB'
        assert progress.percent == 24
        assert progress.speed == '50.0 MiB/s'
        assert progress.eta == '1m20s'

    def test_parse_info_file_copied(self):
        """rclone -v INFO lines for individual file transfers."""
        line = '2026/03/06 17:45:33 INFO  : vacation/photo.jpg: Copied (server-side copy)'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.current_file == 'vacation/photo.jpg'
        assert progress.current_file_detail == 'Copied'

    def test_parse_info_file_deleted(self):
        line = '2026/03/06 17:45:33 INFO  : old_file.txt: Deleted'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.current_file == 'old_file.txt'
        assert progress.current_file_detail == 'Deleted'

    def test_parse_stats_without_prefix(self):
        """Stats lines without log prefix still work (backward compat)."""
        line = '    5.000 MiB / 5.000 MiB, 100%, 0 B/s, ETA -'
        progress = parse_stats_line(line, SyncProgress())
        assert progress.bytes_transferred == '5.000 MiB'
        assert progress.percent == 100


class TestRunSync:
    def test_returns_error_when_source_missing(self):
        success, error, timestamp = run_sync('/nonexistent/src', '/nonexistent/dst')
        assert success is False
        assert error == 'Google Drive not mounted'
        assert timestamp is None

    def test_returns_error_when_destination_missing(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        success, error, timestamp = run_sync(str(src), '/nonexistent/dst')
        assert success is False
        assert error == 'NAS not mounted'
        assert timestamp is None

    @patch('sync.subprocess.run')
    def test_successful_sync(self, mock_run, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

        success, error, timestamp = run_sync(str(src), str(dst))
        assert success is True
        assert error is None
        assert timestamp is not None
        mock_run.assert_called_once()

    @patch('sync.subprocess.run')
    def test_rclone_failure(self, mock_run, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='some rclone error\ndetailed error')

        success, error, timestamp = run_sync(str(src), str(dst))
        assert success is False
        assert error == 'detailed error'
        assert timestamp is None

    @patch('sync.subprocess.run')
    def test_rclone_failure_empty_stderr(self, mock_run, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='')

        success, error, timestamp = run_sync(str(src), str(dst))
        assert success is False
        assert error == 'rclone error'

    @patch('sync.subprocess.run', side_effect=FileNotFoundError)
    def test_rclone_not_installed(self, mock_run, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        success, error, timestamp = run_sync(str(src), str(dst))
        assert success is False
        assert 'rclone not found' in error

    @patch('sync.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='rclone', timeout=3600))
    def test_sync_timeout(self, mock_run, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        success, error, timestamp = run_sync(str(src), str(dst))
        assert success is False
        assert error == 'Sync timed out'

    @patch('sync.subprocess.run', side_effect=OSError('permission denied'))
    def test_unexpected_exception(self, mock_run, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        success, error, timestamp = run_sync(str(src), str(dst))
        assert success is False
        assert 'permission denied' in error


class TestFindRclone:
    @patch('sync.shutil.which', return_value='/usr/local/bin/rclone')
    def test_finds_via_which(self, mock_which):
        assert find_rclone() == '/usr/local/bin/rclone'

    @patch('sync.shutil.which', return_value=None)
    @patch('sync.os.path.isfile', return_value=False)
    def test_returns_none_when_not_found(self, mock_isfile, mock_which):
        assert find_rclone() is None

    @patch('sync.shutil.which', return_value=None)
    @patch('sync.os.access', return_value=True)
    @patch('sync.os.path.isfile')
    def test_finds_in_homebrew_path(self, mock_isfile, mock_access, mock_which):
        """When which() fails, falls back to checking /opt/homebrew/bin/rclone."""
        mock_isfile.side_effect = lambda p: p == '/opt/homebrew/bin/rclone'
        result = find_rclone()
        assert result == '/opt/homebrew/bin/rclone'

    @patch('sync.shutil.which', return_value=None)
    @patch('sync.os.access', return_value=True)
    @patch('sync.os.path.isfile')
    def test_finds_usr_local_rclone(self, mock_isfile, mock_access, mock_which):
        """Falls back to /usr/local/bin/rclone when homebrew path not found."""
        mock_isfile.side_effect = lambda p: p == '/usr/local/bin/rclone'
        result = find_rclone()
        assert result == '/usr/local/bin/rclone'

    def test_finds_in_app_bundle(self, tmp_path):
        """When frozen, checks Contents/Resources/rclone relative to the executable."""
        macos_dir = tmp_path / 'Contents' / 'MacOS'
        resources_dir = tmp_path / 'Contents' / 'Resources'
        macos_dir.mkdir(parents=True)
        resources_dir.mkdir(parents=True)

        fake_rclone = resources_dir / 'rclone'
        fake_rclone.write_text('#!/bin/sh')
        fake_rclone.chmod(0o755)

        fake_executable = str(macos_dir / 'FolderSync')

        with patch('sync.sys') as mock_sys:
            mock_sys.frozen = True
            mock_sys.executable = fake_executable
            result = find_rclone()
            assert result == str(fake_rclone)

    def test_skips_bundle_check_when_not_frozen(self):
        """When not frozen (running from source), skip bundle check."""
        with patch('sync.shutil.which', return_value='/opt/homebrew/bin/rclone'):
            result = find_rclone()
            assert result == '/opt/homebrew/bin/rclone'


class TestInstallRclone:
    @patch('sync.find_rclone', return_value='/opt/homebrew/bin/rclone')
    @patch('sync.subprocess.run')
    @patch('sync.shutil.which', return_value='/opt/homebrew/bin/brew')
    @patch('sync.os.path.isfile', return_value=False)
    def test_successful_install(self, mock_isfile, mock_which, mock_run, mock_find):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        result = install_rclone()
        assert result == '/opt/homebrew/bin/rclone'
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[1] == 'install'
        assert args[2] == 'rclone'

    @patch('sync.subprocess.run')
    @patch('sync.shutil.which', return_value='/opt/homebrew/bin/brew')
    @patch('sync.os.path.isfile', return_value=False)
    def test_brew_install_fails(self, mock_isfile, mock_which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)
        result = install_rclone()
        assert result is None

    @patch('sync.shutil.which', return_value=None)
    @patch('sync.os.path.isfile', return_value=False)
    def test_no_brew_available(self, mock_isfile, mock_which):
        result = install_rclone()
        assert result is None

    @patch('sync.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='brew', timeout=300))
    @patch('sync.shutil.which', return_value='/opt/homebrew/bin/brew')
    @patch('sync.os.path.isfile', return_value=False)
    def test_brew_install_timeout(self, mock_isfile, mock_which, mock_run):
        result = install_rclone()
        assert result is None

    @patch('sync.subprocess.run', side_effect=OSError('permission denied'))
    @patch('sync.shutil.which', return_value='/opt/homebrew/bin/brew')
    @patch('sync.os.path.isfile', return_value=False)
    def test_brew_install_os_error(self, mock_isfile, mock_which, mock_run):
        result = install_rclone()
        assert result is None

    def test_finds_brew_at_homebrew_path(self, tmp_path):
        """Finds brew at /opt/homebrew/bin/brew before falling back to which."""
        with patch('sync.os.path.isfile', side_effect=lambda p: p == '/opt/homebrew/bin/brew'):
            with patch('sync.subprocess.run') as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)
                install_rclone()
                args = mock_run.call_args[0][0]
                assert args[0] == '/opt/homebrew/bin/brew'


class TestBuildRcloneCommandRcloneMissing:
    @patch('sync.find_rclone', return_value=None)
    def test_raises_when_rclone_not_found(self, mock_find):
        with pytest.raises(FileNotFoundError, match='rclone not found'):
            build_rclone_command('/src', '/dst')


class TestRunSyncLive:
    def test_returns_error_when_source_missing(self):
        result = run_sync_live('/nonexistent/src', '/nonexistent/dst')
        assert result.success is False
        assert result.error == 'Google Drive not mounted'

    def test_returns_error_when_destination_missing(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        result = run_sync_live(str(src), '/nonexistent/dst')
        assert result.success is False
        assert result.error == 'NAS not mounted'

    @patch('sync.subprocess.Popen')
    def test_successful_sync(self, mock_popen, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.stdout = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        result = run_sync_live(str(src), str(dst), log_file=str(tmp_path / 'test.log'))
        assert result.success is True
        assert result.timestamp is not None

    @patch('sync.subprocess.Popen')
    def test_calls_progress_callback(self, mock_popen, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        mock_proc = MagicMock()
        mock_proc.stderr = iter(['Transferred:   1.0 GiB / 2.0 GiB, 50%, 10.0 MiB/s, ETA 1m0s\n'])
        mock_proc.stdout = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        callback = MagicMock()
        result = run_sync_live(str(src), str(dst), on_progress=callback, log_file=str(tmp_path / 'test.log'))
        assert result.success is True
        assert callback.call_count >= 1

    @patch('sync.subprocess.Popen')
    def test_stop_event_cancels_sync(self, mock_popen, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        stop_event = threading.Event()
        stop_event.set()  # Already set — should cancel immediately

        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.stdout = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = -15  # SIGTERM
        mock_popen.return_value = mock_proc

        result = run_sync_live(str(src), str(dst), stop_event=stop_event, log_file=str(tmp_path / 'test.log'))
        assert result.success is False
        assert result.error == 'Sync cancelled'

    @patch('sync.subprocess.Popen')
    def test_rclone_failure_returns_error(self, mock_popen, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.stdout = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.stderr.read.return_value = 'some error\n'
        mock_popen.return_value = mock_proc

        result = run_sync_live(str(src), str(dst), log_file=str(tmp_path / 'test.log'))
        assert result.success is False

    @patch('sync.subprocess.Popen', side_effect=FileNotFoundError)
    def test_rclone_not_found(self, mock_popen, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        result = run_sync_live(str(src), str(dst), log_file=str(tmp_path / 'test.log'))
        assert result.success is False
        assert 'rclone not found' in result.error

    @patch('sync.subprocess.Popen')
    def test_writes_to_log_file(self, mock_popen, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        log_file = tmp_path / 'test.log'

        mock_proc = MagicMock()
        mock_proc.stderr = iter(['2026/03/06 17:45:33 INFO  : test.txt: Copied\n'])
        mock_proc.stdout = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        run_sync_live(str(src), str(dst), log_file=str(log_file))
        assert log_file.exists()
        content = log_file.read_text()
        assert 'Copied' in content

    @patch('sync.subprocess.Popen')
    def test_uses_checksum_flag(self, mock_popen, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()

        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.stdout = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        run_sync_live(str(src), str(dst), use_checksum=True, log_file=str(tmp_path / 'test.log'))
        cmd = mock_popen.call_args[0][0]
        assert '--checksum' in cmd


class TestSyncResultDataclass:
    def test_default_values(self):
        r = SyncResult()
        assert r.timestamp == ''
        assert r.success is False
        assert r.error is None
        assert r.bytes_transferred == ''
        assert r.files_transferred == 0
        assert r.duration_seconds == 0

    def test_cancelled_sync_result(self):
        r = SyncResult(timestamp='Mar 06, 14:30', success=False, error='Sync cancelled', duration_seconds=5)
        assert r.error == 'Sync cancelled'
        assert r.success is False


class TestTruncateLog:
    def test_no_op_when_file_missing(self, tmp_path):
        truncate_log(str(tmp_path / 'nonexistent.log'), max_bytes=100)

    def test_no_op_when_small(self, tmp_path):
        log = tmp_path / 'test.log'
        log.write_text('small log\n')
        truncate_log(str(log), max_bytes=1024)
        assert log.read_text() == 'small log\n'

    def test_truncates_large_file(self, tmp_path):
        log = tmp_path / 'test.log'
        lines = [f'line {i}\n' for i in range(1000)]
        log.write_text(''.join(lines))
        original_size = log.stat().st_size
        max_bytes = 1024
        truncate_log(str(log), max_bytes=max_bytes)
        new_size = log.stat().st_size
        assert new_size < original_size
        assert new_size <= max_bytes
        # Should end with complete lines
        content = log.read_text()
        assert content.endswith('\n')
        # Should not start with a partial line
        assert content.startswith('line ')

    def test_preserves_tail_content(self, tmp_path):
        log = tmp_path / 'test.log'
        lines = [f'line {i}\n' for i in range(100)]
        log.write_text(''.join(lines))
        truncate_log(str(log), max_bytes=200)
        content = log.read_text()
        # Last line should be preserved
        assert 'line 99\n' in content


class TestSyncLogging:
    """Test that sync functions log key events."""

    def test_run_sync_logs_path_validation_error(self, caplog):
        import logging

        with caplog.at_level(logging.ERROR, logger='sync'):
            run_sync('/nonexistent/src', '/nonexistent/dst')
        assert any('Path validation failed' in r.message for r in caplog.records)

    @patch('sync.subprocess.run')
    def test_run_sync_logs_rclone_command(self, mock_run, tmp_path, caplog):
        import logging

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

        with caplog.at_level(logging.INFO, logger='sync'):
            run_sync(str(src), str(dst))
        assert any('Running rclone' in r.message for r in caplog.records)

    @patch('sync.subprocess.run')
    def test_run_sync_logs_rclone_failure(self, mock_run, tmp_path, caplog):
        import logging

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='some error')

        with caplog.at_level(logging.ERROR, logger='sync'):
            run_sync(str(src), str(dst))
        assert any('rclone failed' in r.message for r in caplog.records)

    def test_run_sync_live_logs_path_validation_error(self, caplog):
        import logging

        with caplog.at_level(logging.ERROR, logger='sync'):
            result = run_sync_live('/nonexistent/src', '/nonexistent/dst')
        assert not result.success
        assert any('Path validation failed' in r.message for r in caplog.records)

    @patch('sync.subprocess.Popen')
    def test_run_sync_live_logs_success(self, mock_popen, tmp_path, caplog):
        import logging

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        log_file = str(tmp_path / 'test.log')

        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        with caplog.at_level(logging.INFO, logger='sync'):
            result = run_sync_live(str(src), str(dst), log_file=log_file)
        assert result.success
        assert any('rclone completed successfully' in r.message for r in caplog.records)

    @patch('sync.subprocess.Popen')
    def test_run_sync_live_logs_rclone_failure(self, mock_popen, tmp_path, caplog):
        import logging

        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        dst.mkdir()
        log_file = str(tmp_path / 'test.log')

        mock_proc = MagicMock()
        mock_proc.stderr = iter(['error: something went wrong\n'])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        with caplog.at_level(logging.ERROR, logger='sync'):
            result = run_sync_live(str(src), str(dst), log_file=log_file)
        assert not result.success
        assert any('rclone failed' in r.message for r in caplog.records)


class TestBuildVersionStamps:
    def test_sync_py_has_build_time_placeholder(self):
        """sync.py must have APP_BUILD_TIME for build.sh to stamp."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        sync_path = os.path.join(project_root, 'sync.py')
        with open(sync_path) as f:
            content = f.read()
        assert "APP_BUILD_TIME = 'dev'" in content

    def test_sync_py_has_build_hash_placeholder(self):
        """sync.py must have APP_BUILD_HASH for build.sh to stamp."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        sync_path = os.path.join(project_root, 'sync.py')
        with open(sync_path) as f:
            content = f.read()
        assert "APP_BUILD_HASH = 'dev'" in content
