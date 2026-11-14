"""The generic media route must never expose private acquisition reports."""
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch
import pytest

@pytest.fixture
def panel(tmp_path,monkeypatch):
    # Isolate route validation from providers, the database and runtime initialization.
    with patch("conecta_video_ai.settings.load_settings",return_value=SimpleNamespace(output_root=tmp_path)), \
         patch("conecta_video_ai.pipelines.StudioService",return_value=SimpleNamespace()):
        monkeypatch.delitem(sys.modules,"conecta_video_ai.webapp",raising=False)
        module=importlib.import_module("conecta_video_ai.webapp")
    private=tmp_path/"instagram/analytics";private.mkdir(parents=True)
    for name in ["latest.json","observations.sqlite3","informe.html"]:
        (private/name).write_bytes(b"private-data")
    nested=private/"trials/captacion_14d_20261114/latest.json"
    nested.parent.mkdir(parents=True);nested.write_bytes(b"private-data")
    yield module.app.test_client(),tmp_path
    sys.modules.pop("conecta_video_ai.webapp",None)

@pytest.mark.parametrize("path",["instagram/analytics/latest.json","instagram/analytics/observations.sqlite3",
    "instagram/analytics/informe.html","instagram/drafts/../analytics/latest.json",
    "instagram/analytics/trials/captacion_14d_20261114/latest.json"])
def test_private_reports_cannot_be_downloaded_through_generated_route(panel,path):
    client,root=panel
    response=client.get("/generated/"+path)
    assert response.status_code==404 and b"private-data" not in response.data

def test_public_media_still_downloads(panel):
    client,root=panel
    (root/"approved.jpg").write_bytes(b"approved-media")
    response=client.get("/generated/approved.jpg")
    assert response.status_code==200 and response.data==b"approved-media"

def test_symlink_cannot_bypass_private_directory_guard(panel):
    client,root=panel
    try:(root/"alias.json").symlink_to(root/"instagram/analytics/latest.json")
    except OSError:pytest.skip("Symbolic links unavailable in this environment")
    response=client.get("/generated/alias.json")
    assert response.status_code==404 and b"private-data" not in response.data
