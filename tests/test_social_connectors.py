from pathlib import Path

from conecta_video_ai.social_connectors import connector_blueprint
from conecta_video_ai.social_publishers import YouTubePublisher


def test_connector_blueprint_for_youtube_and_tiktok():
    yt = connector_blueprint("youtube")
    tk = connector_blueprint("tiktok")

    assert "YOUTUBE_CLIENT_ID" in yt.required_env
    assert "YOUTUBE_CLIENT_SECRET" in yt.required_env
    assert "TIKTOK_CLIENT_KEY" in tk.required_env
    assert "TIKTOK_CLIENT_SECRET" in tk.required_env


def test_youtube_multipart_builder_contains_metadata_and_video_bytes():
    metadata = {"snippet": {"title": "test"}, "status": {"privacyStatus": "public"}}
    video_data = b"fake-video-bytes"
    body, boundary = YouTubePublisher._build_multipart(metadata, video_data, "video/mp4")

    assert boundary
    assert b"application/json" in body
    assert b"video/mp4" in body
    assert b"fake-video-bytes" in body
