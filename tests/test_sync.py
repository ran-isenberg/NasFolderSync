import subprocess
from unittest.mock import patch

from sync import SyncProgress, build_rclone_command, parse_stats_line, run_sync, validate_paths


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


class TestBuildRcloneCommand:
    def test_default_log_file(self):
        cmd = build_rclone_command('/src', '/dst')
        assert cmd[0] == 'rclone'
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
        assert '--stats=1s' in cmd
        assert '--stats-one-line' in cmd
        assert '--progress' in cmd

    def test_checksum_disabled_by_default(self):
        cmd = build_rclone_command('/src', '/dst')
        assert '--checksum' not in cmd

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
