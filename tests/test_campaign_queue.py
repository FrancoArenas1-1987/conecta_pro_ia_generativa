import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from conecta_video_ai.campaign_queue import (
    CampaignQueue, CampaignSelectionError, campaign_root, run_campaign_slot,
    mark_image_slot_completed,
)

NOW = datetime(2026, 11, 13, 15, tzinfo=timezone.utc)


def entry(code='hogar'):
    return {'campaign_id': code, 'enabled': True, 'approval_status': 'approved'}


def manifest(*entries):
    return {'enabled': True, 'min_interval_hours': 24, 'repeat_after_days': 7, 'entries': list(entries or [entry()])}


def test_campaign_needs_approval_and_enabled_switch(tmp_path):
    q = CampaignQueue(tmp_path)
    assert q.claim({'enabled': False, 'entries': [entry()]}, NOW) is None
    bad = entry(); bad['approval_status'] = 'pending_review'
    assert q.claim(manifest(bad), NOW) is None
    assert q.claim(manifest(), NOW)['campaign']['campaign_id'] == 'hogar'


def test_cadence_alternates_and_repeats_only_after_seven_days(tmp_path):
    q = CampaignQueue(tmp_path); m = manifest(entry('hogar'), entry('mascotas'))
    first = q.claim(m, NOW); q.finish(first['id'], 'published')
    assert q.claim(m, NOW + timedelta(days=1)) is None  # ordinary image required
    q.mark_image_slot()
    assert q.claim(m, NOW + timedelta(hours=23)) is None
    second = q.claim(m, NOW + timedelta(days=1))
    assert second['campaign']['campaign_id'] == 'mascotas'
    q.finish(second['id'], 'published'); q.mark_image_slot()
    assert q.claim(m, NOW + timedelta(days=6)) is None
    assert q.claim(m, NOW + timedelta(days=7))['campaign']['campaign_id'] == 'hogar'


def test_concurrent_workers_can_claim_only_one_slot(tmp_path):
    q = CampaignQueue(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: q.claim(manifest(), NOW), range(4)))
    assert sum(r is not None for r in results) == 1


@pytest.mark.parametrize('state', ['claimed', 'publishing', 'uncertain', 'partial'])
def test_unresolved_outcomes_never_republish_automatically(tmp_path, state):
    q = CampaignQueue(tmp_path); a = q.claim(manifest(), NOW)
    q.finish(a['id'], state); q.mark_image_slot()
    assert CampaignQueue(tmp_path).claim(manifest(), NOW + timedelta(days=30)) is None


def make_service(tmp_path, *, fail=None, duplicate_target=False):
    settings = SimpleNamespace(output_root=tmp_path/'runs', instagram_drafts_root=tmp_path/'drafts')
    r = campaign_root(settings); r.mkdir(parents=True)
    video = r/'test.mp4'; video.write_bytes(b'fake video - actual encoding is checked in production preflight')
    cover = r/'cover.png'; Image.new('RGB', (1080,1920), 'white').save(cover)
    item = entry(); item.update(video='test.mp4', cover='cover.png', caption='Find contacts.', duration_seconds=20,
        sha256=hashlib.sha256(video.read_bytes()).hexdigest(), cover_sha256=hashlib.sha256(cover.read_bytes()).hexdigest())
    (r/'manifest.json').write_text(json.dumps(manifest(item)))
    calls = []
    class Publisher:
        def remote_url_reachable(self, url): return True, 'ok'
        def stage_local_video_for_public_url(self, **kwargs):
            calls.append('stage'); return 'https://example.test/unpublished.mp4'
        def send(self, channel):
            calls.append(channel)
            if channel == fail: raise RuntimeError('network timeout')
            return {'story_id' if channel=='fb_story' else 'post_id': channel, 'published_at': NOW.isoformat()}
        def publish_reel_video(self, **kw): return self.send('reel')
        def publish_story_video(self, **kw): return self.send('story')
        def publish_facebook_video(self, **kw): return self.send('fb')
        def publish_facebook_story_video(self, **kw): return self.send('fb_story')
    target = {'name':'primary','meta_page_id':'page','meta_instagram_user_id':'ig',
              'publish_instagram':True,'crosspost_facebook':True,'publish_facebook_story':True}
    targets = [target, dict(target, name='duplicate')] if duplicate_target else [target]
    service = SimpleNamespace(settings=settings,
        instagram_engine=SimpleNamespace(_validate_ig_video=lambda **kw: {'passed':True,'score':100}),
        _load_instagram_publish_targets=lambda:targets,
        _preflight_publish_targets=lambda rows:(rows, {'selected':len(rows)}),
        _build_instagram_publisher=lambda target:Publisher())
    return service, r, calls


def test_deliveries_are_persisted_and_normal_mode_is_unchanged(tmp_path):
    service,root,calls=make_service(tmp_path, duplicate_target=True)
    result=run_campaign_slot(service,now=NOW)
    assert calls == ['stage','reel','story','fb','fb_story']
    assert result['publication']['status']=='ok'
    assert result['draft']['status']=='published'
    assert result['draft']['video_qc']['passed']
    with CampaignQueue(root).connect() as db:
        assert db.execute("select count(*) from deliveries where status='published'").fetchone()[0] == 4
    mark_image_slot_completed(service.settings)
    assert run_campaign_slot(service, now=NOW+timedelta(days=1)) is None


def test_partial_success_preserves_receipts_and_quarantines_retry(tmp_path):
    service,root,calls=make_service(tmp_path,fail='story')
    with pytest.raises(RuntimeError,match='timeout'):run_campaign_slot(service,now=NOW)
    with CampaignQueue(root).connect() as db:
        assert db.execute('select status from attempts').fetchone()[0]=='partial'
        assert db.execute("select channel,status from deliveries where channel='instagram_story'").fetchone()[1]=='sending'
        assert db.execute("select count(*) from deliveries where status='published'").fetchone()[0]==3
    draft=json.loads(next(service.settings.instagram_drafts_root.glob('*/draft.json')).read_text())
    assert draft['status']=='published_with_errors' and draft['post_id']=='reel'
    mark_image_slot_completed(service.settings)
    assert run_campaign_slot(service,now=NOW+timedelta(days=30)) is None
    assert calls.count('reel')==1


def test_tampered_asset_is_blocked_before_any_external_request(tmp_path):
    service,root,calls=make_service(tmp_path); (root/'test.mp4').write_bytes(b'tampered')
    with pytest.raises(RuntimeError,match='checksum'):run_campaign_slot(service,now=NOW)
    assert calls==[]


def test_corrupt_manifest_is_distinct_from_delivery_failure(tmp_path):
    service,root,calls=make_service(tmp_path); (root/'manifest.json').write_text('{bad')
    with pytest.raises(CampaignSelectionError):run_campaign_slot(service,now=NOW)
    assert calls==[]


def test_outside_path_is_not_accepted(tmp_path):
    service,root,calls=make_service(tmp_path)
    m=json.loads((root/'manifest.json').read_text());m['entries'][0]['video']='../outside.mp4';(root/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(RuntimeError,match='outside'):run_campaign_slot(service,now=NOW)
    assert calls==[]

@pytest.fixture
def runner(monkeypatch, tmp_path):
    import importlib.util
    from conecta_video_ai.settings import AppSettings
    path = Path(__file__).resolve().parents[1] / 'scripts/run_instagram_autopublish_once.py'
    spec = importlib.util.spec_from_file_location('campaign_runner_test',path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    settings=AppSettings(output_root=tmp_path/'runs',instagram_drafts_root=tmp_path/'drafts',instagram_state_path=tmp_path/'state.json')
    engine=SimpleNamespace(sync_asset_catalog=lambda:{},sweep_library_quality=lambda **kw:{})
    service=SimpleNamespace(settings=settings,instagram_engine=engine,_instagram_publish_media_mode=lambda:'image_only')
    monkeypatch.setattr(module,'load_settings',lambda:settings)
    monkeypatch.setattr(module,'StudioService',lambda _:service)
    monkeypatch.setattr(module,'publish_window_status',lambda **kw:{'allowed':True})
    monkeypatch.setattr(module,'_active_antispam_cooldown_until',lambda _:None)
    monkeypatch.setattr(module,'_active_publish_interval_guard',lambda _:(False,None,None))
    monkeypatch.setattr('sys.argv',['runner'])
    return module,service,settings


@pytest.mark.parametrize('guard',['window','antispam','interval'])
def test_runner_guards_run_before_campaign_selection(runner,monkeypatch,guard):
    module,service,settings=runner
    def forbidden(*args,**kwargs):raise AssertionError('campaign must not run behind an active guard')
    monkeypatch.setattr(module,'run_campaign_slot',forbidden)
    if guard=='window':monkeypatch.setattr(module,'publish_window_status',lambda **kw:{'allowed':False})
    elif guard=='antispam':monkeypatch.setattr(module,'_active_antispam_cooldown_until',lambda _:'2099-01-01')
    else:monkeypatch.setattr(module,'_active_publish_interval_guard',lambda _:(True,'100',20))
    module.main()


def test_runner_campaign_replaces_one_image_slot(runner,monkeypatch):
    module,service,settings=runner
    monkeypatch.setattr(module,'run_campaign_slot',lambda _:{'draft':{'post_id':'published-reel'},'publication':{'status':'ok'},'campaign_id':'hogar'})
    def forbidden(*args,**kwargs):raise AssertionError('do not publish both paths in one slot')
    service.run_instagram_auto_cycle=forbidden
    monkeypatch.setattr(module,'mark_image_slot_completed',forbidden)
    module.main()
    log=(settings.output_root/'instagram/automation_hourly_log.jsonl').read_text()
    assert 'hogar' in log and 'published-reel' in log


def test_runner_continues_images_on_invalid_campaign_configuration(runner,monkeypatch):
    module,service,settings=runner;calls=[]
    def bad(_):raise CampaignSelectionError('Invalid manifest')
    monkeypatch.setattr(module,'run_campaign_slot',bad)
    service.run_instagram_auto_cycle=lambda **kw: calls.append('image') or {'draft':{},'publication':{'status':'ok'}}
    monkeypatch.setattr(module,'mark_image_slot_completed',lambda _:calls.append('mark'))
    module.main();assert calls==['image','mark']


def test_stable_https_asset_avoids_temporary_facebook_staging(tmp_path):
    service,root,calls=make_service(tmp_path)
    m=json.loads((root/'manifest.json').read_text());m['entries'][0]['public_video_url']='https://conectaproia.cl/campanas/test.mp4';(root/'manifest.json').write_text(json.dumps(m))
    run_campaign_slot(service,now=NOW)
    assert 'stage' not in calls and 'reel' in calls


def test_image_success_is_preserved_if_campaign_bookkeeping_fails(runner,monkeypatch):
    module,service,settings=runner
    monkeypatch.setattr(module,'run_campaign_slot',lambda _:None)
    service.run_instagram_auto_cycle=lambda **kw:{'draft':{},'publication':{'status':'ok'}}
    def bad(_):raise OSError('read-only queue')
    monkeypatch.setattr(module,'mark_image_slot_completed',bad)
    module.main()
    row=json.loads((settings.output_root/'instagram/automation_hourly_log.jsonl').read_text().splitlines()[-1])
    assert row['ok'] and row['campaign_state_error']=='read-only queue'
