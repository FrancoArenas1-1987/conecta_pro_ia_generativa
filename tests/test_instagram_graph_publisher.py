from pathlib import Path

import pytest

from conecta_video_ai.exceptions import GenerationError
from conecta_video_ai.instagram_graph_publisher import InstagramGraphPublisher
from conecta_video_ai.settings import AppSettings


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        output_root=tmp_path / "output",
        tracking_root=tmp_path / "tracking",
        context_path=tmp_path / "context.yaml",
        assets_root=tmp_path / "assets",
        meta_access_token="token",
        meta_page_id="page_1",
        meta_instagram_user_id="ig_1",
    )


def test_video_status_summary_ready_and_failed_detection():
    ready, failed, known, detail = InstagramGraphPublisher._video_status_summary(
        {"status": {"video_status": "ready"}}
    )
    assert ready is True
    assert failed is False
    assert known is True
    assert "READY" in detail

    ready, failed, known, detail = InstagramGraphPublisher._video_status_summary(
        {"status": {"video_status": "processing", "errors": [{"code": 1}]}}
    )
    assert ready is False
    assert failed is True
    assert known is True
    assert "STATUS_ERRORS_PRESENT" in detail


def test_stage_local_video_waits_until_ready_before_returning_source(monkeypatch, tmp_path: Path):
    settings = _settings(tmp_path)
    publisher = InstagramGraphPublisher(settings)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-video")

    monkeypatch.setattr(publisher, "resolve_page_access_token", lambda: "page_token")
    monkeypatch.setattr(
        publisher,
        "_http_multipart",
        lambda **kwargs: {"id": "video_1"},
    )
    monkeypatch.setattr(
        publisher,
        "_remote_url_reachable",
        lambda url, timeout=20: (True, "http_200"),
    )

    calls = {"n": 0}

    def _fake_http(*, method: str, path: str, params: dict, access_token: str | None = None):
        assert method == "GET"
        assert path == "/video_1"
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "id": "video_1",
                "source": "https://cdn.test/v.mp4",
                "status": {"video_status": "processing"},
            }
        return {
            "id": "video_1",
            "source": "https://cdn.test/v.mp4",
            "status": {"video_status": "ready"},
        }

    monkeypatch.setattr(publisher, "_http", _fake_http)
    monkeypatch.setattr("conecta_video_ai.instagram_graph_publisher.time.sleep", lambda _s: None)

    out = publisher.stage_local_video_for_public_url(video_path=video, description="desc")
    assert out == "https://cdn.test/v.mp4"
    assert calls["n"] >= 2


def test_stage_local_video_raises_when_status_is_failed(monkeypatch, tmp_path: Path):
    settings = _settings(tmp_path)
    publisher = InstagramGraphPublisher(settings)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-video")

    monkeypatch.setattr(publisher, "resolve_page_access_token", lambda: "page_token")
    monkeypatch.setattr(
        publisher,
        "_http_multipart",
        lambda **kwargs: {"id": "video_2"},
    )
    monkeypatch.setattr(
        publisher,
        "_http",
        lambda **kwargs: {
            "id": "video_2",
            "source": "https://cdn.test/v.mp4",
            "status": {"video_status": "failed"},
        },
    )
    monkeypatch.setattr("conecta_video_ai.instagram_graph_publisher.time.sleep", lambda _s: None)

    with pytest.raises(GenerationError):
        publisher.stage_local_video_for_public_url(video_path=video, description="desc")


def test_publish_facebook_story_photo_stages_unpublished_photo_first(monkeypatch, tmp_path: Path):
    settings = _settings(tmp_path)
    publisher = InstagramGraphPublisher(settings)
    monkeypatch.setattr(publisher, "resolve_page_access_token", lambda: "page_token")
    calls: list[tuple[str, dict]] = []

    def _fake_http(*, method: str, path: str, params: dict, access_token: str | None = None):
        calls.append((path, dict(params)))
        if path.endswith("/photos"):
            return {"id": "photo_1"}
        if path.endswith("/photo_stories"):
            return {"id": "story_1"}
        raise AssertionError(path)

    monkeypatch.setattr(publisher, "_http", _fake_http)
    result = publisher.publish_facebook_story_photo(image_url="https://cdn.test/story.jpg")

    assert result["status"] == "published"
    assert result["story_id"] == "story_1"
    assert result["photo_id"] == "photo_1"
    assert calls == [
        ("/page_1/photos", {"url": "https://cdn.test/story.jpg", "published": "false"}),
        ("/page_1/photo_stories", {"photo_id": "photo_1"}),
    ]


def test_publish_carousel_post_creates_children_then_carousel(monkeypatch, tmp_path: Path):
    settings = _settings(tmp_path)
    publisher = InstagramGraphPublisher(settings)
    calls: list[tuple[str, dict]] = []
    ids = iter(["child_1", "child_2", "carousel_1"])

    def _fake_http(*, method: str, path: str, params: dict, access_token: str | None = None):
        calls.append((path, dict(params)))
        if path == "/ig_1/media":
            return {"id": next(ids)}
        if path == "/ig_1/media_publish":
            return {"id": "media_1"}
        if path == "/media_1":
            return {"id": "media_1", "permalink": "https://ig.test/p/1", "media_type": "CAROUSEL_ALBUM"}
        if path in {"/child_1", "/child_2", "/carousel_1"}:
            return {"id": path.strip("/"), "status_code": "FINISHED"}
        raise AssertionError(path)

    monkeypatch.setattr(publisher, "_http", _fake_http)
    result = publisher.publish_carousel_post(
        image_urls=["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"],
        caption="Caption",
    )

    assert result["status"] == "published"
    assert result["post_id"] == "media_1"
    assert calls[0] == ("/ig_1/media", {"image_url": "https://cdn.test/1.jpg", "is_carousel_item": "true"})
    assert calls[2] == ("/ig_1/media", {"image_url": "https://cdn.test/2.jpg", "is_carousel_item": "true"})
    assert calls[4] == (
        "/ig_1/media",
        {"media_type": "CAROUSEL", "children": "child_1,child_2", "caption": "Caption"},
    )


def test_publish_facebook_multi_photo_uses_attached_media(monkeypatch, tmp_path: Path):
    settings = _settings(tmp_path)
    publisher = InstagramGraphPublisher(settings)
    monkeypatch.setattr(publisher, "resolve_page_access_token", lambda: "page_token")
    calls: list[tuple[str, dict]] = []
    ids = iter(["photo_1", "photo_2"])

    def _fake_http(*, method: str, path: str, params: dict, access_token: str | None = None):
        calls.append((path, dict(params)))
        if path == "/page_1/photos":
            return {"id": next(ids)}
        if path == "/page_1/feed":
            return {"id": "page_1_post_1"}
        raise AssertionError(path)

    monkeypatch.setattr(publisher, "_http", _fake_http)
    result = publisher.publish_facebook_multi_photo(
        image_urls=["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"],
        caption="Caption",
    )

    assert result["status"] == "published"
    assert result["post_id"] == "page_1_post_1"
    assert calls[0] == ("/page_1/photos", {"url": "https://cdn.test/1.jpg", "published": "false"})
    assert calls[1] == ("/page_1/photos", {"url": "https://cdn.test/2.jpg", "published": "false"})
    assert calls[2][0] == "/page_1/feed"
    assert calls[2][1]["message"] == "Caption"
    assert '"media_fbid": "photo_1"' in calls[2][1]["attached_media"]
    assert '"media_fbid": "photo_2"' in calls[2][1]["attached_media"]


def story_publisher(tmp_path,monkeypatch, *, fail_finish=False, missing_post=False):
    p=InstagramGraphPublisher(_settings(tmp_path));calls=[];checkpoints=[]
    monkeypatch.setattr(p,'resolve_page_access_token',lambda:'page_token')
    monkeypatch.setattr('conecta_video_ai.instagram_graph_publisher.time.sleep',lambda _:None)
    def http(*,method,path,params,access_token=None):
        calls.append((method,path,dict(params)))
        if method=='POST' and params.get('upload_phase')=='start':
            return {'video_id':'123','upload_url':'https://rupload.facebook.com/video-upload/v21.0/123'}
        if method=='POST' and params.get('upload_phase')=='finish':
            assert checkpoints[-1]['phase']=='finishing'
            assert params['video_state']=='PUBLISHED'
            if fail_finish:raise GenerationError('network timeout')
            return {'success':True} if missing_post else {'success':True,'post_id':'story_123'}
        if path=='/123':
            finishing=any(r[2].get('upload_phase')=='finish' for r in calls)
            return {'status':{'video_status':'ready','uploading_phase':{'status':'complete'},
                              'publishing_phase':{'status':'complete' if finishing else 'not_started'}}}
        if path=='/page_1/stories':
            return {'data':[{'post_id':'wrong','media_id':'456','status':'published'},
                            {'post_id':'story_123','media_id':'123','status':'published'}]}
        raise AssertionError((method,path,params))
    monkeypatch.setattr(p,'_http',http)
    def transfer(**kw):
        calls.append(('UPLOAD',kw['upload_url'],{'source':kw['video_url']}))
        return {'success':True}
    monkeypatch.setattr(p,'_upload_story_video',transfer)
    return p,calls,checkpoints


def test_facebook_story_video_follows_start_transfer_finish_and_confirmation(tmp_path,monkeypatch):
    p,calls,states=story_publisher(tmp_path,monkeypatch)
    result=p.publish_facebook_story_video(video_url='https://cdn.test/story.mp4',progress=states.append)
    assert result['status']=='published' and result['story_id']=='story_123' and result['video_id']=='123'
    assert [r[2].get('upload_phase') for r in calls if r[0]=='POST']==['start','finish']
    assert [r['phase'] for r in states]==['starting','session_created','transferred','finishing','finish_acknowledged','confirmed']
    assert calls[1][0]=='UPLOAD'


def test_facebook_story_finish_timeout_is_never_retried(tmp_path,monkeypatch):
    p,calls,states=story_publisher(tmp_path,monkeypatch,fail_finish=True)
    with pytest.raises(GenerationError,match='timeout'):
        p.publish_facebook_story_video(video_url='https://cdn.test/story.mp4',progress=states.append)
    assert sum(c[2].get('upload_phase')=='finish' for c in calls)==1
    assert states[-1]=={'phase':'finishing','video_id':'123','publication_may_have_occurred':True}


def test_facebook_story_success_acknowledgement_resolves_real_story_id(tmp_path,monkeypatch):
    p,calls,states=story_publisher(tmp_path,monkeypatch,missing_post=True)
    result=p.publish_facebook_story_video(video_url='https://cdn.test/story.mp4',progress=states.append)
    assert result['story_id']=='story_123'


def test_facebook_story_transfer_failure_never_calls_finish(tmp_path,monkeypatch):
    p,calls,states=story_publisher(tmp_path,monkeypatch)
    def fail(**kw):raise GenerationError('transfer rejected')
    monkeypatch.setattr(p,'_upload_story_video',fail)
    with pytest.raises(GenerationError,match='transfer'):
        p.publish_facebook_story_video(video_url='https://cdn.test/story.mp4',progress=states.append)
    assert not any(c[2].get('upload_phase')=='finish' for c in calls)
    assert states[-1]['video_id']=='123'


@pytest.mark.parametrize('url',[
    'http://rupload.facebook.com/video-upload/v21.0/123',
    'https://example.test/video-upload/v21.0/123',
    'https://rupload.facebook.com.evil.test/video-upload/v21.0/123',
    'https://rupload.facebook.com/video-upload/v21.0/456'
])
def test_story_upload_rejects_untrusted_destination_before_sending_token(tmp_path,url):
    p=InstagramGraphPublisher(_settings(tmp_path))
    with pytest.raises(GenerationError,match='destination'):
        p._upload_story_video(upload_url=url,video_id='123',video_url='https://cdn.test/story.mp4',page_token='secret')


def test_story_binary_transfer_uses_meta_upload_url_and_hosted_file_header(tmp_path,monkeypatch):
    import io,json
    p=InstagramGraphPublisher(_settings(tmp_path));seen=[]
    def open_request(request,timeout):
        seen.append(request)
        return io.BytesIO(json.dumps({'success':True}).encode())
    monkeypatch.setattr('conecta_video_ai.instagram_graph_publisher.urlopen',open_request)
    result=p._upload_story_video(upload_url='https://rupload.facebook.com/video-upload/v21.0/123',video_id='123',
                                 video_url='https://cdn.test/story.mp4',page_token='page_token')
    assert result['success']
    assert seen[0].method=='POST'
    assert seen[0].get_header('Authorization')=='OAuth page_token'
    assert seen[0].get_header('File_url')=='https://cdn.test/story.mp4'


def test_story_processing_error_never_reports_published(tmp_path,monkeypatch):
    p=InstagramGraphPublisher(_settings(tmp_path))
    monkeypatch.setattr(p,'_http',lambda **kw:{'status':{'video_status':'error','processing_phase':{'errors':[{'code':1}]}}})
    with pytest.raises(GenerationError,match='processing failed'):
        p._wait_story_phase(video_id='123',page_token='token',published=True)
