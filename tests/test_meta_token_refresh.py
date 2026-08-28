import os
from pathlib import Path

from conecta_video_ai.meta_token_refresh import update_env_file


def test_update_env_file_replaces_and_appends(tmp_path: Path):
    env = tmp_path / '.env'
    env.write_text('A=1\nMETA_ACCESS_TOKEN=old\n', encoding='utf-8')

    backup = update_env_file(
        env_path=env,
        updates={
            'META_ACCESS_TOKEN': 'new_token',
            'META_PAGE_ID': '123',
        },
        create_backup=True,
    )

    assert backup is not None
    assert backup.exists()

    content = env.read_text(encoding='utf-8')
    assert 'META_ACCESS_TOKEN=new_token' in content
    assert 'META_PAGE_ID=123' in content
    assert 'A=1' in content


def test_update_env_file_creates_when_missing(tmp_path: Path):
    env = tmp_path / '.env'
    backup = update_env_file(
        env_path=env,
        updates={'META_USER_ACCESS_TOKEN': 'abc'},
        create_backup=True,
    )

    assert backup is None
    content = env.read_text(encoding='utf-8')
    assert 'META_USER_ACCESS_TOKEN=abc' in content


def test_update_env_file_prunes_old_backups(tmp_path: Path):
    env = tmp_path / '.env'
    env.write_text('A=1\n', encoding='utf-8')

    old1 = tmp_path / '.env.bak_20200101_000001'
    old2 = tmp_path / '.env.bak_20200101_000002'
    old3 = tmp_path / '.env.bak_20200101_000003'
    for f in (old1, old2, old3):
        f.write_text('OLD=1\n', encoding='utf-8')

    os.utime(old1, (1000, 1000))
    os.utime(old2, (1001, 1001))
    os.utime(old3, (1002, 1002))

    backup = update_env_file(
        env_path=env,
        updates={'META_PAGE_ID': '123'},
        create_backup=True,
        backups_to_keep=2,
    )

    backups = sorted(tmp_path.glob('.env.bak_*'))
    assert backup is not None
    assert backup.exists()
    assert len(backups) == 2
