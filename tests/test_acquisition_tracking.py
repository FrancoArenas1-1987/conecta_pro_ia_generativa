from urllib.parse import urlparse,parse_qs
import re
from conecta_video_ai.acquisition_tracking import tracking_code_for,tracked_whatsapp_url,whatsapp_enquiries

def test_draft_reference_is_stable_and_distinguishes_publications():
    a=tracking_code_for("draft-one")
    assert re.fullmatch("CP-[A-F0-9]{12}",a)
    assert a==tracking_code_for("draft-one") and a!=tracking_code_for("draft-two")

def test_tracking_keeps_contact_and_prefills_context():
    code=tracking_code_for("draft")
    url=tracked_whatsapp_url("https://api.whatsapp.com/send?phone=56983434503",code,"Electricidad")
    parsed=urlparse(url);message=parse_qs(parsed.query)["text"][0]
    assert parsed.hostname=="wa.me" and parsed.path=="/56983434503"
    assert "Electricidad" in message and code in message

def test_no_database_request_is_made_without_published_references(monkeypatch):
    monkeypatch.setenv("CP_DB_PASSWORD","must-not-be-read")
    assert whatsapp_enquiries([{"tracking_code":None}])=={"status":"no_references_published","per_reference":{}}

def test_missing_database_configuration_does_not_turn_into_zero_clients(monkeypatch):
    for key in ["CP_DB_HOST","CP_DB_NAME","CP_DB_USER","CP_DB_PASSWORD"]:monkeypatch.delenv(key,raising=False)
    result=whatsapp_enquiries([{"tracking_code":tracking_code_for("ad")}])
    assert result["status"]=="database_not_configured" and result["per_reference"] is None

def test_enquiry_collection_is_read_only_parameterized_and_does_not_export_people(monkeypatch):
    import psycopg
    for key in ["CP_DB_HOST","CP_DB_NAME","CP_DB_USER","CP_DB_PASSWORD"]:monkeypatch.setenv(key,"test")
    code=tracking_code_for("ad");seen={}
    class DB:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query,params):
            assert "COUNT(DISTINCT inbound.customer_wa_id)" in query
            assert params==([code],)
            return self
        def fetchall(self):return [(code,2)]
    def connect(**kwargs):
        seen.update(kwargs);return DB()
    monkeypatch.setattr(psycopg,"connect",connect)
    result=whatsapp_enquiries([{"tracking_code":code}])
    assert "default_transaction_read_only=on" in seen["options"]
    assert result["per_reference"]=={code:2}
    assert "customer_wa_id" not in str(result)
