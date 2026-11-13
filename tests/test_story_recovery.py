import hashlib,json,importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from conecta_video_ai.campaign_queue import CampaignQueue

path=Path(__file__).resolve().parents[1]/"scripts/recover_facebook_story.py"
spec=importlib.util.spec_from_file_location("story_recovery",path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def setup(tmp_path):
    root=tmp_path/"campaigns";q=CampaignQueue(root)
    target=hashlib.sha256(b"page|ig").hexdigest()[:20]
    video=root/"approved.mp4";video.write_bytes(b"approved")
    (root/"manifest.json").write_text(json.dumps({"entries":[{"campaign_id":"guia","approval_status":"approved","video":video.name,
        "sha256":hashlib.sha256(video.read_bytes()).hexdigest(),"public_video_url":"https://example.test/approved.mp4"}]}))
    with q.connect() as db:
        db.execute("INSERT INTO attempts VALUES ('attempt','guia','draft','2026-11-13T12:00:00+00:00','partial',NULL,?)",
            ("facebook_story: Meta Graph HTTP 400: The parameter upload_phase is required",))
        for channel in ["instagram_reel","instagram_story","facebook_video"]:
            db.execute("INSERT INTO deliveries VALUES ('attempt',?,?,'published',?)",(target,channel,json.dumps({"post_id":channel})))
        db.execute("INSERT INTO deliveries VALUES ('attempt',?,'facebook_story','sending',NULL)",(target,))
    class Publisher:
        page_id="page";ig_user_id="ig";calls=0
        def publish_facebook_story_video(self,*,video_url,progress):
            self.calls+=1;progress({"phase":"finishing","video_id":"123","publication_may_have_occurred":True})
            return {"story_id":"resolved"}
    return root,q,Publisher()

def test_recovery_only_sends_the_missing_destination_and_is_idempotent(tmp_path):
    root,q,p=setup(tmp_path)
    assert module.recover(root,"attempt",p,verify=False)["status"]=="reviewed"
    assert p.calls==0
    result=module.recover(root,"attempt",p,execute=True,verify=False)
    assert result["status"]=="published" and p.calls==1
    assert module.recover(root,"attempt",p,execute=True,verify=False)["status"]=="already_resolved"
    assert p.calls==1
    with q.connect() as db:
        assert db.execute("select count(*) from deliveries where status='published'").fetchone()[0]==4
        assert json.loads(db.execute("select receipt from deliveries where channel='instagram_reel'").fetchone()[0])=={"post_id":"instagram_reel"}

def test_recovery_refuses_an_uncertain_finish_or_second_retry(tmp_path):
    root,q,p=setup(tmp_path)
    def failed(**kw):
        p.calls+=1;kw["progress"]({"phase":"finishing","video_id":"123","publication_may_have_occurred":True})
        raise RuntimeError("network timeout")
    p.publish_facebook_story_video=failed
    with pytest.raises(RuntimeError):module.recover(root,"attempt",p,execute=True,verify=False)
    with pytest.raises(ValueError,match="reconcile"):module.recover(root,"attempt",p,execute=True,verify=False)
    assert p.calls==1
    with q.connect() as db:
        data=json.loads(db.execute("select receipt from deliveries where channel='facebook_story'").fetchone()[0])
        assert data["video_id"]=="123" and data["phase"]=="finishing"

def test_recovery_refuses_unrelated_delivery_errors(tmp_path):
    root,q,p=setup(tmp_path)
    with q.connect() as db:db.execute("UPDATE attempts SET error='request timed out'")
    with pytest.raises(ValueError,match="reconcile"):module.recover(root,"attempt",p,execute=True,verify=False)
    assert p.calls==0
