import json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from conecta_video_ai import publication_supply as supply
from conecta_video_ai.campaign_queue import CampaignQueue,run_campaign_slot,campaign_root
from conecta_video_ai.pipelines import StudioService
from conecta_video_ai.service_images import save_registry,read_registry


def item(code="specific",services=None,scope="specific"):
    return {"campaign_id":code,"enabled":True,"approval_status":"approved","availability_scope":scope,
        "required_service_codes":services if services is not None else ["traductor"]}


def test_no_supply_skips_specific_before_claim_and_keeps_general(monkeypatch,tmp_path):
    monkeypatch.setattr(supply,"live_supply",lambda:{"traductor":{"provider_count":0}})
    m={"enabled":True,"entries":[item(),item("general",[],"general")]}
    queue=CampaignQueue(tmp_path);selected=queue.claim(supply.eligible_manifest(m))
    assert selected["campaign"]["campaign_id"]=="general"
    with queue.connect() as db:assert db.execute("SELECT count(*) FROM attempts WHERE campaign='specific'").fetchone()[0]==0
    assert m["entries"][0]["enabled"] is True


def test_database_failure_never_uses_old_provider_counts(monkeypatch):
    def fail():raise supply.SupplyBlocked("unavailable")
    monkeypatch.setattr(supply,"live_supply",fail)
    m={"entries":[{**item(),"provider_count":999},item("general",[],"general")]}
    assert [i["campaign_id"] for i in supply.eligible_manifest(m)["entries"]]==["general"]


@pytest.mark.parametrize("bad",[{},item(services=[]),item(services=["traductor"],scope="general"),item(services=["bad/code"]),item(services="traductor")])
def test_missing_or_inconsistent_scope_is_blocked(bad):
    with pytest.raises(supply.SupplyBlocked):supply.required_codes(bad)
    assert not supply.eligible_manifest({"entries":[{**bad,"enabled":True,"approval_status":"approved"}]})["entries"]


def test_all_named_services_required_aliases_canonicalized():
    with pytest.raises(supply.SupplyBlocked,match="traductor"):
        supply.assert_services(["legal","traductores_ingles_espanol"],supply={"abogado":{"provider_count":2}})
    checked=supply.assert_services(["legal"],supply={"abogado":{"provider_count":2}})
    assert checked["service_codes"]==["abogado"] and checked["provider_counts"]=={"abogado":2}


def test_paused_campaign_stays_paused_when_supply_returns(monkeypatch):
    monkeypatch.setattr(supply,"live_supply",lambda:{"traductor":{"provider_count":3}})
    assert not supply.eligible_manifest({"entries":[{**item(),"enabled":False}]})["entries"]


def test_live_sql_is_read_only_and_exports_only_service_counts(monkeypatch):
    for k in ["HOST","NAME","USER","PASSWORD"]:monkeypatch.setenv("CP_DB_"+k,"configured")
    seen={}
    class Database:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query):
            seen["query"]=query;return SimpleNamespace(fetchall=lambda:[("legal","Abogado",2),("traductor","Traductor",0)])
    def connect(**kwargs):seen.update(kwargs);return Database()
    monkeypatch.setitem(sys.modules,"psycopg",SimpleNamespace(connect=connect))
    actual=supply.live_supply()
    assert actual=={"abogado":{"name":"Abogado","provider_count":2},"traductor":{"name":"Traductor","provider_count":0}}
    assert "default_transaction_read_only=on" in seen["options"]
    for condition in ["ps.active=true","p.active=true","p.blocked_until<=now()","sc.active=true"]:assert condition in seen["query"]
    assert seen["connect_timeout"]==5


def test_connection_error_redacts_credentials(monkeypatch):
    for k in ["HOST","NAME","USER","PASSWORD"]:monkeypatch.setenv("CP_DB_"+k,"secret-value")
    def connect(**kwargs):raise RuntimeError("password=secret-value")
    monkeypatch.setitem(sys.modules,"psycopg",SimpleNamespace(connect=connect))
    with pytest.raises(supply.SupplyBlocked) as exc:supply.live_supply()
    assert "secret-value" not in str(exc.value)


def test_registry_refresh_preserves_approval_hash_and_unavailable_service(monkeypatch,tmp_path):
    path=tmp_path/"registry.json";save_registry(path,{"services":{"traductor":{"active":True,"provider_count":99,"status":"approved","sha256":"abc","image":"old.png"},"abogado":{"active":False,"provider_count":0,"status":"needs_review"}}})
    monkeypatch.setattr(supply,"live_supply",lambda:{"traductor":{"provider_count":0},"abogado":{"provider_count":3}})
    supply.synchronize_registry(path);result=read_registry(path)
    assert result["services"]["traductor"]=={"active":False,"provider_count":0,"status":"approved","sha256":"abc","image":"old.png"}
    assert result["services"]["abogado"]["active"] and result["services"]["abogado"]["status"]=="needs_review"


def test_registry_is_not_overwritten_when_database_fails(monkeypatch,tmp_path):
    path=tmp_path/"registry.json";save_registry(path,{"services":{}});before=path.read_bytes()
    def fail():raise supply.SupplyBlocked("unavailable")
    monkeypatch.setattr(supply,"live_supply",fail)
    with pytest.raises(supply.SupplyBlocked):supply.synchronize_registry(path)
    assert path.read_bytes()==before


def test_campaign_rechecks_supply_before_touching_meta(monkeypatch,tmp_path):
    calls=[]
    available=iter([{"traductor":{"provider_count":1}},{"traductor":{"provider_count":0}}])
    monkeypatch.setattr(supply,"live_supply",lambda:next(available))
    settings=SimpleNamespace(output_root=tmp_path,instagram_drafts_root=tmp_path/"drafts",instagram_whatsapp_client_url="https://wa.me/56983434503")
    root=campaign_root(settings);root.mkdir(parents=True)
    # An invalid media type fails before the second availability check; instead use a fully checked image.
    from PIL import Image
    import hashlib
    from conecta_video_ai.publication_checks import caption_digest
    caption="ConectaProIA. Buscar contactos es gratis. El servicio lo cobra cada profesional. WhatsApp https://wa.me/56983434503"
    media=root/"feed.jpg";Image.new("RGB",(1080,1350),"white").save(media)
    e={**item(),"media_type":"image","publish_stories":False,"image":media.name,"sha256":hashlib.sha256(media.read_bytes()).hexdigest(),"caption":caption,"caption_sha256":caption_digest(caption)}
    (root/"manifest.json").write_text(json.dumps({"enabled":True,"entries":[e]}))
    service=SimpleNamespace(settings=settings,_load_instagram_publish_targets=lambda:calls.append("Meta"))
    with pytest.raises(RuntimeError,match="No active providers"):run_campaign_slot(service)
    assert not calls
    with CampaignQueue(root).connect() as db:
        assert db.execute("SELECT status FROM attempts").fetchone()[0]=="failed"
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0]==0


def test_regular_draft_blocks_before_any_media_or_provider_work(monkeypatch):
    monkeypatch.setattr(supply,"live_supply",lambda:{"traductor":{"provider_count":0}})
    service=SimpleNamespace(instagram_engine=SimpleNamespace(get_draft=lambda _:{"asset_category_id":"traductor"}))
    with pytest.raises(supply.SupplyBlocked,match="No active providers"):
        StudioService.publish_instagram_draft(service,draft_id="existing",simulate=False)


def test_carousel_supply_failure_happens_before_meta(monkeypatch,tmp_path):
    import scripts.run_instagram_carousel_once as carousel
    monkeypatch.setattr(carousel,"load_settings",lambda:SimpleNamespace(instagram_whatsapp_client_url="https://wa.me/56983434503"))
    monkeypatch.setattr(carousel,"validate_caption",lambda *a,**k:{"passed":True})
    monkeypatch.setattr(carousel,"validate_images",lambda *a,**k:{"passed":True})
    categories=["traductor","abogado","desarrollo_web"];paths=[tmp_path/(c+".png") for c in categories]
    monkeypatch.setattr(carousel,"load_assets",lambda _:{c:[p] for c,p in zip(categories,paths)})
    monkeypatch.setattr(supply,"live_supply",lambda:{"abogado":{"provider_count":2},"desarrollo_web":{"provider_count":2}})
    monkeypatch.setattr(carousel,"InstagramGraphPublisher",lambda _:pytest.fail("Meta must not be contacted"))
    manifest={"caption":"checked","slides":[str(tmp_path/(str(i)+".jpg")) for i in range(5)],"assets_root":str(tmp_path),"theme":{"categories":categories},"services":[{"category_id":c,"image_path":str(p)} for c,p in zip(categories,paths)]}
    with pytest.raises(supply.SupplyBlocked,match="traductor"):carousel.publish_carousel(manifest)
