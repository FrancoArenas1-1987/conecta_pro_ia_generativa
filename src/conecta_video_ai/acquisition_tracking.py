"""Creative references in WhatsApp links and anonymous, read-only enquiry counts."""
from __future__ import annotations
import hashlib,os,re
from urllib.parse import urlencode
from .publication_checks import phone_from_url

REFERENCE=re.compile(r"CP-[A-F0-9]{12}\Z")

def tracking_code_for(identifier):
    return "CP-"+hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:12].upper()

def tracked_whatsapp_url(url,reference,service):
    if not REFERENCE.fullmatch(reference):raise ValueError("Invalid acquisition reference")
    phone=phone_from_url(url)
    if not re.fullmatch(r"\d{8,15}",phone):raise ValueError("Invalid WhatsApp contact")
    label=" ".join(str(service).split())[:100]
    message=f"Hola, busco contactos de {label}. Referencia {reference}"
    return "https://wa.me/"+phone+"?"+urlencode({"text":message})

def whatsapp_enquiries(records):
    codes=sorted({r.get("tracking_code") for r in records if REFERENCE.fullmatch(str(r.get("tracking_code") or ""))})
    if not codes:return {"status":"no_references_published","per_reference":{}}
    required=["CP_DB_HOST","CP_DB_NAME","CP_DB_USER","CP_DB_PASSWORD"]
    if not all(os.getenv(k) for k in required):return {"status":"database_not_configured","per_reference":None}
    try:
        import psycopg
        with psycopg.connect(host=os.environ["CP_DB_HOST"],port=os.getenv("CP_DB_PORT","5432"),
             dbname=os.environ["CP_DB_NAME"],user=os.environ["CP_DB_USER"],password=os.environ["CP_DB_PASSWORD"],
             connect_timeout=5,options="-c default_transaction_read_only=on -c statement_timeout=10000") as db:
            rows=db.execute("""
                SELECT matched.code[1] AS reference,COUNT(DISTINCT inbound.customer_wa_id)
                FROM inbound_messages inbound
                CROSS JOIN LATERAL regexp_matches(upper(coalesce(inbound.text,'')), '(CP-[A-F0-9]{12})','g') AS matched(code)
                WHERE inbound.created_at>=now()-interval '45 days' AND matched.code[1]=ANY(%s)
                GROUP BY matched.code[1]
            """,(codes,)).fetchall()
        counts=dict(rows)
        return {"status":"available","window_days":45,"per_reference":{code:int(counts.get(code,0)) for code in codes},
                "meaning":"Distinct WhatsApp contacts per creative reference, shared across channels; not sales or contracts."}
    except Exception as exc:
        # Never print connection errors containing database credentials.
        return {"status":"unavailable","error_type":type(exc).__name__,"per_reference":None}


def whatsapp_enquiries_window(records, *, since, until):
    """Count anonymous contacts in [since, until), never export messages or people."""
    from datetime import datetime
    if not isinstance(since, datetime) or not isinstance(until, datetime) or since.tzinfo is None or until.tzinfo is None:
        raise ValueError("Attribution window must use timezone-aware datetimes")
    if until <= since:
        raise ValueError("Attribution window must be positive")
    codes=sorted({r.get("tracking_code") for r in records if REFERENCE.fullmatch(str(r.get("tracking_code") or ""))})
    base={"since":since.isoformat(),"until":until.isoformat(),
          "meaning":"Distinct contacts mentioning published creative references; shared across channels, not sales."}
    if not codes:return {**base,"status":"no_references_published","per_reference":{},"distinct_contacts":None}
    required=["CP_DB_HOST","CP_DB_NAME","CP_DB_USER","CP_DB_PASSWORD"]
    if not all(os.getenv(k) for k in required):
        return {**base,"status":"database_not_configured","per_reference":None,"distinct_contacts":None}
    try:
        import psycopg
        with psycopg.connect(host=os.environ["CP_DB_HOST"],port=os.getenv("CP_DB_PORT","5432"),
             dbname=os.environ["CP_DB_NAME"],user=os.environ["CP_DB_USER"],password=os.environ["CP_DB_PASSWORD"],
             connect_timeout=5,options="-c default_transaction_read_only=on -c statement_timeout=10000") as db:
            rows=db.execute("""
                WITH matched AS (
                    SELECT inbound.customer_wa_id, matched.code[1] AS reference
                    FROM inbound_messages inbound
                    CROSS JOIN LATERAL regexp_matches(upper(coalesce(inbound.text,'')), '(CP-[A-F0-9]{12})','g') AS matched(code)
                    WHERE inbound.created_at >= %s AND inbound.created_at < %s AND matched.code[1]=ANY(%s)
                )
                SELECT reference,COUNT(DISTINCT customer_wa_id)
                FROM matched GROUP BY GROUPING SETS ((reference),())
            """,(since,until,codes)).fetchall()
        counts={code:int(n) for code,n in rows if code is not None}
        total=next((int(n) for code,n in rows if code is None),None)
        return {**base,"status":"available","per_reference":{code:counts.get(code,0) for code in codes},
                "distinct_contacts":total}
    except Exception as exc:
        return {**base,"status":"unavailable","error_type":type(exc).__name__,"per_reference":None,"distinct_contacts":None}
