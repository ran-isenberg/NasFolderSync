import json
import os

from sync import DEFAULT_CONFIG, load_config, save_config


def test_load_config_returns_defaults_when_no_file(tmp_path):
    config_file = str(tmp_path / 'nonexistent.json')
    config = load_config(config_file)
    assert config == DEFAULT_CONFIG


def test_load_config_creates_file_on_first_launch(tmp_path):
    config_file = str(tmp_path / 'fresh.json')
    assert not os.path.exists(config_file)
    config = load_config(config_file)
    assert os.path.exists(config_file)
    with open(config_file) as f:
        saved = json.load(f)
    assert saved == DEFAULT_CONFIG
    assert config == DEFAULT_CONFIG


def test_load_config_returns_defaults_copy(tmp_path):
    config_file = str(tmp_path / 'nonexistent.json')
    config = load_config(config_file)
    config['source'] = '/changed'
    assert DEFAULT_CONFIG['source'] != '/changed'


def test_load_config_merges_with_defaults(tmp_path):
    config_file = str(tmp_path / 'config.json')
    partial = {'source': '/my/drive', 'interval_minutes': 10}
    with open(config_file, 'w') as f:
        json.dump(partial, f)

    config = load_config(config_file)
    assert config['source'] == '/my/drive'
    assert config['interval_minutes'] == partial['interval_minutes']
    assert config['destination'] == DEFAULT_CONFIG['destination']
    assert config['enabled'] is True


def test_load_config_overrides_all_defaults(tmp_path):
    config_file = str(tmp_path / 'config.json')
    custom = {
        'source': '/a',
        'destination': '/b',
        'interval_minutes': 1,
        'enabled': False,
        'use_checksum': True,
    }
    with open(config_file, 'w') as f:
        json.dump(custom, f)

    config = load_config(config_file)
    for key, value in custom.items():
        assert config[key] == value


def test_save_config_writes_valid_json(tmp_path):
    config_file = str(tmp_path / 'config.json')
    config = {'source': '/src', 'destination': '/dst', 'interval_minutes': 3, 'enabled': True}
    save_config(config, config_file)

    with open(config_file) as f:
        loaded = json.load(f)
    assert loaded == config


def test_save_and_load_roundtrip(tmp_path):
    config_file = str(tmp_path / 'config.json')
    config = {'source': '/my/src', 'destination': '/my/dst', 'interval_minutes': 15, 'enabled': False, 'use_checksum': True}
    save_config(config, config_file)
    loaded = load_config(config_file)
    for key, value in config.items():
        assert loaded[key] == value
