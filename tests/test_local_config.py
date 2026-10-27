import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


def copy_generator(tmp_path):
    source = Path(__file__).resolve().parent.parent / 'scripts' / 'generate-local-env.py'
    target = tmp_path / 'scripts' / source.name
    target.parent.mkdir()
    shutil.copyfile(source, target)
    return target


def run_generator(path, **extra):
    environment = os.environ.copy()
    environment['MYSQL_DATA_DIR'] = str(path.parent.parent / 'mysql-data')
    environment.update(extra)
    return subprocess.run([sys.executable, str(path)], env=environment, capture_output=True, text=True)


def test_private_local_secrets_are_preserved_and_cloud_token_not_copied(tmp_path):
    script = copy_generator(tmp_path)
    assert run_generator(script, META_PAGE_ACCESS_TOKEN='test-token-never-copy').returncode == 0
    config = tmp_path / '.env'
    first = config.read_bytes()
    assert b'test-token-never-copy' not in first
    assert b'META_PAGE_ACCESS_TOKEN=' not in first
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert run_generator(script).returncode == 0
    assert config.read_bytes() == first


def test_missing_credentials_never_regenerate_over_existing_mysql_data(tmp_path):
    script = copy_generator(tmp_path)
    data = tmp_path / 'mysql-data'
    data.mkdir()
    (data / 'existing-data').write_text('retained')
    result = run_generator(script)
    assert result.returncode != 0
    assert not (tmp_path / '.env').exists()
    assert (data / 'existing-data').read_text() == 'retained'


def test_secret_generator_refuses_symlink_without_overwriting_target(tmp_path):
    script = copy_generator(tmp_path)
    original = tmp_path / 'user-file'
    original.write_text('unchanged')
    (tmp_path / '.env').symlink_to(original)
    assert run_generator(script).returncode != 0
    assert original.read_text() == 'unchanged'
