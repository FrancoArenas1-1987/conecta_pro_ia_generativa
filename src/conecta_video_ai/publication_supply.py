"""Live service availability for organic advertising. SQL reads only; no customer data."""
from __future__ import annotations
import os,re
from datetime import datetime,timezone
from .service_images import canonical,read_registry,save_registry

class SupplyBlocked(RuntimeError):
    """The advertised services could not be confirmed before sending."""


def live_supply():
    required=["CP_DB_HOST","CP_DB_NAME","CP_DB_USER","CP_DB_PASSWORD"]
    if not all(os.getenv(k) for k in required):
        raise SupplyBlocked("Service availability cannot be checked; publication withheld")
    try:
        import psycopg
        with psycopg.connect(host=os.environ["CP_DB_HOST"],port=os.getenv("CP_DB_PORT","5432"),
            dbname=os.environ["CP_DB_NAME"],user=os.environ["CP_DB_USER"],password=os.environ["CP_DB_PASSWORD"],
            connect_timeout=5,options="-c default_transaction_read_only=on -c statement_timeout=10000") as db:
            rows=db.execute("""
                SELECT sc.code,sc.name,count(DISTINCT p.id)
                FROM public.service_catalog sc
                LEFT JOIN public.provider_services ps ON ps.service_code=sc.code AND ps.active=true
                LEFT JOIN public.providers p ON p.id=ps.provider_id AND p.active=true
                    AND (p.blocked_until IS NULL OR p.blocked_until<=now())
                WHERE sc.active=true GROUP BY sc.code,sc.name
            """).fetchall()
        return {canonical(str(code)):{"name":str(name),"provider_count":int(count)} for code,name,count in rows}
    except SupplyBlocked:raise
    except Exception as exc:
        raise SupplyBlocked("Service availability cannot be checked ("+type(exc).__name__+"); publication withheld") from None


def required_codes(item):
    scope=item.get("availability_scope");codes=item.get("required_service_codes")
    if scope not in {"general","specific"} or not isinstance(codes,list):
        raise SupplyBlocked("Approved advertising needs an explicit availability scope and service codes")
    if any(not isinstance(c,str) or not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,100}",c) for c in codes):
        raise SupplyBlocked("Invalid advertised service code")
    codes=sorted({canonical(c) for c in codes})
    if (scope=="general" and codes) or (scope=="specific" and not codes):
        raise SupplyBlocked("Advertising scope does not match its service codes")
    return codes


def assert_services(codes,*,supply=None):
    if not codes:raise SupplyBlocked("Specific advertising must identify its services")
    codes=sorted({canonical(str(c)) for c in codes})
    supply=live_supply() if supply is None else supply
    missing=[c for c in codes if int(supply.get(c,{}).get("provider_count",0))<1]
    if missing:raise SupplyBlocked("No active providers for advertised service: "+", ".join(missing))
    return {"checked_at":datetime.now(timezone.utc).isoformat(),"service_codes":codes,
        "provider_counts":{c:int(supply[c]["provider_count"]) for c in codes},"status":"available",
        "meaning":"Active, unblocked providers; not a guarantee of appointments or coverage in every commune"}


def assert_campaign(item):
    codes=required_codes(item)
    return assert_services(codes) if codes else {"status":"general_directory_ad","service_codes":[]}


def eligible_manifest(manifest):
    """Filter before claiming a queue slot. Unknown metadata/supply never means available."""
    entries=[];supply=None;failed=False
    for item in manifest.get("entries",[]):
        if not item.get("enabled") or item.get("approval_status")!="approved":continue
        try:
            codes=required_codes(item)
            if codes:
                if failed:continue
                if supply is None:
                    try:supply=live_supply()
                    except SupplyBlocked:failed=True;continue
                assert_services(codes,supply=supply)
            entries.append(item)
        except SupplyBlocked:continue
    return {**manifest,"entries":entries}


def synchronize_registry(path):
    """Refresh counts/active flags, preserving all image hashes and editorial approvals."""
    registry=read_registry(path)
    if not registry:raise SupplyBlocked("Approved service registry missing")
    supply=live_supply();changed=[]
    for code,row in registry["services"].items():
        current=supply.get(canonical(code));count=int((current or {}).get("provider_count",0))
        active=bool(current and count>0)
        if row.get("active")!=active or row.get("provider_count")!=count:changed.append(code)
        row.update(active=active,provider_count=count)
    registry["availability_checked_at"]=datetime.now(timezone.utc).isoformat()
    save_registry(path,registry)
    return {"status":"available","changed_service_count":len(changed),"active_services":sum(x["provider_count"]>0 for x in supply.values())}


def assert_draft(draft):
    # Curated image category drives the actual caption; reject unknown legacy drafts.
    if "availability_scope" in draft:return assert_campaign(draft)
    code=str(draft.get("asset_category_id") or draft.get("category_id") or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,100}",code) or code in {"general","campaign","sin_clasificar"}:
        raise SupplyBlocked("Draft must identify the advertised service before publishing")
    return assert_services([code])
