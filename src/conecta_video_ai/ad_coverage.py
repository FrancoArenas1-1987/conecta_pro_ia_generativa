"""Private coverage of live service supply by approved advertising assets."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json
from .campaign_queue import atomic_json
from .publication_supply import live_supply,required_codes,SupplyBlocked
from .service_images import read_registry,approved_paths,canonical


def analyze_coverage(supply,registry,manifest,assets_root):
    offered={c:r for c,r in supply.items() if int(r.get("provider_count",0))>0}
    primaries=set(approved_paths(registry,Path(assets_root))) & set(offered)
    covered=set(primaries);blocked=[];general=[];campaigns=[]
    for entry in (manifest.get("entries",[]) if manifest.get("enabled") else []):
        if not entry.get("enabled") or entry.get("approval_status")!="approved":continue
        identifier=entry.get("campaign_id")
        try:codes=required_codes(entry)
        except SupplyBlocked:blocked.append({"campaign_id":identifier,"reason":"invalid_scope"});continue
        missing=[c for c in codes if c not in offered]
        if missing:blocked.append({"campaign_id":identifier,"reason":"no_active_providers","service_codes":missing});continue
        if not codes:general.append(identifier)
        else:covered.update(codes)
        campaigns.append(identifier)
    gaps=[{"code":c,"name":r["name"],"provider_count":r["provider_count"]} for c,r in offered.items() if c not in covered]
    gaps.sort(key=lambda r:(-r["provider_count"],r["name"]))
    return {"status":"available","active_services_with_providers":len(offered),"services_with_specific_ad":len(covered),
        "services_without_specific_ad":len(gaps),"coverage_percent":round(100*len(covered)/len(offered),1) if offered else None,
        "approved_regular_services":len(primaries),"eligible_campaigns":len(campaigns),"general_campaigns":general,
        "held_campaigns":blocked,"gaps":gaps,
        "meaning":"Supply counts are not demand, sales, appointments or availability in every commune. General directory ads do not cover every named category."}


def refresh_coverage_report(settings):
    folder=Path(settings.output_root)/"instagram/analytics";folder.mkdir(parents=True,exist_ok=True)
    try:
        registry=read_registry(Path(settings.output_root)/"instagram/catalog/service_images.json")
        manifest=json.loads((Path(settings.output_root)/"instagram/campaigns/manifest.json").read_text(encoding="utf-8-sig"))
        assets=Path(settings.instagram_publish_assets_root)
        if not assets.is_absolute():assets=Path(__file__).resolve().parents[2]/assets
        result=analyze_coverage(live_supply(),registry,manifest,assets)
    except Exception as exc:
        result={"status":"unavailable","error_type":type(exc).__name__,"active_services_with_providers":None,
            "services_with_specific_ad":None,"services_without_specific_ad":None,"coverage_percent":None}
    result["generated_at"]=datetime.now(timezone.utc).isoformat()
    atomic_json(folder/"coverage.json",result)
    return result
