import hashlib,json
from types import SimpleNamespace
from conecta_video_ai.ad_coverage import analyze_coverage,refresh_coverage_report

def test_general_ads_do_not_hide_supply_gaps_and_missing_supply_is_held(tmp_path):
    p=tmp_path/"a.png";p.write_bytes(b"approved")
    registry={"services":{"electricidad":{"active":True,"status":"approved","provider_count":99,"image":"a.png","sha256":hashlib.sha256(p.read_bytes()).hexdigest()}}}
    def entry(id,codes):return {"campaign_id":id,"enabled":True,"approval_status":"approved","availability_scope":"specific" if codes else "general","required_service_codes":codes}
    m={"enabled":True,"entries":[entry("guide",[]),entry("restaurant",["comida_preparada_restaurante"]),entry("translation",["traductor"])]}
    supply={"electricidad":{"name":"Electricidad","provider_count":2},"comida_preparada_restaurante":{"name":"Restaurante","provider_count":20},"jardineria":{"name":"Jardinería","provider_count":3},"traductor":{"name":"Traductor","provider_count":0}}
    r=analyze_coverage(supply,registry,m,tmp_path)
    assert r["active_services_with_providers"]==3 and r["services_with_specific_ad"]==2
    assert r["gaps"]==[{"code":"jardineria","name":"Jardinería","provider_count":3}]
    assert r["held_campaigns"]==[{"campaign_id":"translation","reason":"no_active_providers","service_codes":["traductor"]}]
    assert r["general_campaigns"]==["guide"]


def test_failed_coverage_query_never_reports_zero_gaps(tmp_path,monkeypatch):
    import conecta_video_ai.ad_coverage as module
    monkeypatch.setattr(module,"read_registry",lambda _: {"services":{}})
    p=tmp_path/"instagram/campaigns";p.mkdir(parents=True);(p/"manifest.json").write_text('{"entries":[]}')
    def fail():raise RuntimeError("private connection string")
    monkeypatch.setattr(module,"live_supply",fail)
    result=refresh_coverage_report(SimpleNamespace(output_root=tmp_path,instagram_publish_assets_root=tmp_path))
    assert result["status"]=="unavailable" and result["services_without_specific_ad"] is None
    raw=(tmp_path/"instagram/analytics/coverage.json").read_text();assert "private connection string" not in raw
