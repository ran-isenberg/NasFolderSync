import os
import subprocess

import pytest


class TestGenerateIcon:
    def test_generates_iconset_pngs(self, tmp_path, monkeypatch):
        """generate_icon.py creates all required PNG frames in the iconset directory."""
        monkeypatch.chdir(tmp_path)
        result = subprocess.run(
            [os.path.join(os.environ.get('VIRTUAL_ENV', '.venv'), 'bin', 'python'), 'generate_icon.py'],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(__file__)),
            timeout=30,
        )
        # The script writes to cwd, but we run it from the project root
        # so check the project's icon.iconset directory
        project_root = os.path.dirname(os.path.dirname(__file__))
        iconset_dir = os.path.join(project_root, 'icon.iconset')

        assert result.returncode == 0, f'generate_icon.py failed: {result.stderr}'
        assert os.path.isdir(iconset_dir)

        # Check standard sizes exist
        for size in [16, 32, 64, 128, 256, 512, 1024]:
            png = os.path.join(iconset_dir, f'icon_{size}x{size}.png')
            assert os.path.isfile(png), f'Missing {png}'
            assert os.path.getsize(png) > 0

        # Check @2x retina variants
        for size in [16, 32, 64, 128, 256, 512]:
            png = os.path.join(iconset_dir, f'icon_{size}x{size}@2x.png')
            assert os.path.isfile(png), f'Missing {png}'

        # Check icns was created
        icns = os.path.join(project_root, 'FolderSync.icns')
        assert os.path.isfile(icns)

        # Cleanup
        import shutil

        shutil.rmtree(iconset_dir, ignore_errors=True)

    def test_icon_is_valid_png(self):
        """The generated icon is a valid PNG with RGBA transparency."""
        from PIL import Image

        from generate_icon import draw_icon

        img = draw_icon(256)
        assert img.size == (256, 256)
        assert img.mode == 'RGBA'

        # Should have some transparent pixels (corners of the folder)
        pixels = list(img.get_flattened_data())
        has_transparent = any(p[3] == 0 for p in pixels)
        assert has_transparent, 'Icon should have transparent background'

        # Should have some non-transparent pixels (the folder itself)
        has_opaque = any(p[3] == 255 for p in pixels)
        assert has_opaque, 'Icon should have opaque content'

    def test_icon_sizes_are_correct(self):
        """draw_icon produces images of the requested size."""
        from generate_icon import draw_icon

        for size in [16, 32, 128, 512]:
            img = draw_icon(size)
            assert img.size == (size, size)


class TestSpecFile:
    def test_spec_references_icns(self):
        """The PyInstaller spec file references the icon."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        spec_path = os.path.join(project_root, 'FolderSync.spec')
        with open(spec_path) as f:
            content = f.read()
        assert "icon='FolderSync.icns'" in content

    def test_icns_file_exists(self):
        """The .icns file exists in the project root (needed for build)."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        icns_path = os.path.join(project_root, 'FolderSync.icns')
        assert os.path.isfile(icns_path), 'FolderSync.icns must exist for PyInstaller build'

    def test_spec_has_lsuielement(self):
        """The spec sets LSUIElement so the app is menu-bar only."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        spec_path = os.path.join(project_root, 'FolderSync.spec')
        with open(spec_path) as f:
            content = f.read()
        assert "'LSUIElement': True" in content


class TestBuildShellScript:
    def test_build_script_exists_and_executable(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        build_sh = os.path.join(project_root, 'build.sh')
        assert os.path.isfile(build_sh)
        assert os.access(build_sh, os.X_OK)

    def test_build_script_generates_icon_before_pyinstaller(self):
        """Icon generation must happen before PyInstaller runs."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        build_sh = os.path.join(project_root, 'build.sh')
        with open(build_sh) as f:
            content = f.read()

        icon_pos = content.find('generate_icon.py')
        pyinstaller_pos = content.find('pyinstaller')
        assert icon_pos != -1, 'build.sh must call generate_icon.py'
        assert pyinstaller_pos != -1, 'build.sh must call pyinstaller'
        assert icon_pos < pyinstaller_pos, 'Icon generation must happen before PyInstaller'

    def test_build_script_bundles_rclone(self):
        """build.sh must copy rclone into the app bundle."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        build_sh = os.path.join(project_root, 'build.sh')
        with open(build_sh) as f:
            content = f.read()
        assert 'Contents/Resources/rclone' in content

    def test_build_script_stamps_build_time(self):
        """build.sh must stamp APP_BUILD_TIME in sync.py before PyInstaller."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        build_sh = os.path.join(project_root, 'build.sh')
        with open(build_sh) as f:
            content = f.read()
        assert 'APP_BUILD_TIME' in content
        assert 'APP_BUILD_HASH' in content
        # Stamp must happen before pyinstaller
        stamp_pos = content.find('APP_BUILD_TIME')
        pyinstaller_pos = content.find('pyinstaller')
        assert stamp_pos < pyinstaller_pos, 'Build stamping must happen before PyInstaller'

    def test_build_script_restores_sync_py(self):
        """build.sh must restore sync.py after stamping (via sync.py.bak)."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        build_sh = os.path.join(project_root, 'build.sh')
        with open(build_sh) as f:
            content = f.read()
        assert 'sync.py.bak' in content
        # Backup before pyinstaller, restore after
        backup_pos = content.find('cp sync.py sync.py.bak')
        restore_pos = content.find('mv sync.py.bak sync.py')
        pyinstaller_pos = content.find('pyinstaller')
        assert backup_pos != -1, 'build.sh must backup sync.py'
        assert restore_pos != -1, 'build.sh must restore sync.py'
        assert backup_pos < pyinstaller_pos < restore_pos

    def test_build_script_uses_hdiutil_for_dmg(self):
        """build.sh should use hdiutil create for DMG generation."""
        project_root = os.path.dirname(os.path.dirname(__file__))
        build_sh = os.path.join(project_root, 'build.sh')
        with open(build_sh) as f:
            content = f.read()
        assert 'hdiutil create' in content


class TestMakefileUninstall:
    def test_makefile_has_uninstall_target(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        makefile = os.path.join(project_root, 'Makefile')
        with open(makefile) as f:
            content = f.read()
        assert 'uninstall:' in content

    def test_makefile_uninstall_removes_app(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        makefile = os.path.join(project_root, 'Makefile')
        with open(makefile) as f:
            content = f.read()
        assert '/Applications/FolderSync.app' in content

    def test_makefile_uninstall_removes_config_files(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        makefile = os.path.join(project_root, 'Makefile')
        with open(makefile) as f:
            content = f.read()
        assert '~/.foldersync.json' in content
        assert '~/.foldersync-history.json' in content
        assert '~/foldersync.log' in content
