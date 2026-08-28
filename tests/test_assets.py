from pathlib import Path

from conecta_video_ai.assets import AssetLibrary


def test_asset_library_best_match(tmp_path: Path):
    folder = tmp_path / "kinesiologia"
    folder.mkdir(parents=True)
    image = folder / "kine_post.png"
    image.write_bytes(b"fake")

    lib = AssetLibrary(tmp_path)
    match = lib.best_match("kinesiologia respiratoria")

    assert match.path == image


def test_asset_library_indexes_audio_items(tmp_path: Path):
    folder = tmp_path / "music"
    folder.mkdir(parents=True)
    audio = folder / "track_story.wav"
    audio.write_bytes(b"fake-audio")

    lib = AssetLibrary(tmp_path)
    paths = [item.path for item in lib.audio_items]
    assert audio in paths
