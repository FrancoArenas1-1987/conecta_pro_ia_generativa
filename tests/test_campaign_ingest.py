from types import SimpleNamespace
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from check_campaign_ingest import IngestOnlyPublisher
from conecta_video_ai.instagram_graph_publisher import InstagramGraphPublisher

def publisher():
    return IngestOnlyPublisher(SimpleNamespace(meta_graph_version="v21.0",
        meta_access_token="test-only",meta_page_id="page",meta_instagram_user_id="ig"))

@pytest.mark.parametrize("path", ["/ig/media_publish","/page/feed","/page/photos"])
def test_ingest_check_blocks_other_writes_before_network(path,monkeypatch):
    def unexpected(**kwargs):pytest.fail("Network called for forbidden write")
    monkeypatch.setattr(InstagramGraphPublisher,"_http",unexpected)
    with pytest.raises(RuntimeError,match="Only unpublished"):
        publisher()._http(method="POST",path=path,params={})

def test_ingest_check_cannot_publish_a_ready_container():
    with pytest.raises(RuntimeError,match="Publishing is forbidden"):
        publisher().publish_media_container(creation_id="container")
