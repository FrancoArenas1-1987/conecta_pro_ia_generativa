"""Recover only the legacy Facebook Story rejection that created no upload session."""
from pathlib import Path
import argparse,hashlib,json,sqlite3,sys
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from conecta_video_ai.settings import load_settings
from conecta_video_ai.instagram_graph_publisher import InstagramGraphPublisher
from conecta_video_ai.campaign_queue import CampaignQueue,atomic_json,campaign_root,safe_error
from conecta_video_ai.publication_checks import verify_public_video

def recover(root,attempt_id,publisher,*,execute=False,verify=True):
    root=Path(root);queue=CampaignQueue(root)
    with queue.connect() as db:
        db.row_factory=sqlite3.Row
        attempt=db.execute("SELECT * FROM attempts WHERE id=?",(attempt_id,)).fetchone()
        if not attempt:raise ValueError("Unknown campaign attempt")
        attempt=dict(attempt)
        rows=[dict(r) for r in db.execute("SELECT * FROM deliveries WHERE attempt=?",(attempt_id,))]
    target=[r for r in rows if r["channel"]=="facebook_story"]
    if len(target)!=1:raise ValueError("Recovery requires one exact Facebook Story destination")
    target=target[0]
    if target["status"]=="published":return {"status":"already_resolved","receipt":json.loads(target["receipt"])}
    error=attempt.get("error") or ""
    if (attempt["status"]!="partial" or target["status"]!="sending" or target.get("receipt")
            or "The parameter upload_phase is required" not in error or "HTTP 400" not in error):
        raise ValueError("Outcome is not the known legacy rejection; reconcile it before any retry")
    if any(r["status"]!="published" for r in rows if r["channel"]!="facebook_story"):
        raise ValueError("Other destinations are unresolved")
    identity=str(publisher.page_id)+"|"+str(publisher.ig_user_id)
    if hashlib.sha256(identity.encode()).hexdigest()[:20]!=target["target"]:
        raise ValueError("Configured publishing destination differs from recorded destination")
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8-sig"))
    entry=next(e for e in manifest["entries"] if e["campaign_id"]==attempt["campaign"])
    if entry.get("approval_status")!="approved":raise ValueError("Campaign is not approved")
    video=(root/entry["video"]).resolve()
    if not video.is_relative_to(root.resolve()) or hashlib.sha256(video.read_bytes()).hexdigest()!=entry["sha256"]:
        raise ValueError("Campaign video changed")
    if verify:verify_public_video(entry["public_video_url"],sha256=entry["sha256"],size_bytes=video.stat().st_size)
    if not execute:return {"status":"reviewed","campaign":attempt["campaign"],"channel":"facebook_story","other_destinations_preserved":len(rows)-1}
    folder=root/"recoveries";folder.mkdir(exist_ok=True)
    at=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with sqlite3.connect(queue.path) as src,sqlite3.connect(folder/(attempt_id+"_"+at+".sqlite3")) as dst:src.backup(dst)
    with queue.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current=db.execute("SELECT status,error FROM attempts WHERE id=?",(attempt_id,)).fetchone()
        receipt=db.execute("SELECT receipt FROM deliveries WHERE attempt=? AND target=? AND channel='facebook_story'",(attempt_id,target["target"])).fetchone()
        if current!=("partial",error) or not receipt or receipt[0]:raise ValueError("Recovery state changed")
        db.execute("UPDATE attempts SET status='recovering' WHERE id=?",(attempt_id,))
        db.execute("UPDATE deliveries SET receipt=? WHERE attempt=? AND target=? AND channel='facebook_story'",
                   (json.dumps({"phase":"recovery_started","legacy_error":error}),attempt_id,target["target"]))
    try:
        result=publisher.publish_facebook_story_video(video_url=entry["public_video_url"],
            progress=lambda state:queue.delivery_progress(attempt_id,target["target"],"facebook_story",state))
        if not (result.get("story_id") or result.get("post_id")):raise ValueError("Missing Story receipt")
        queue.delivery_finished(attempt_id,target["target"],"facebook_story",result)
        queue.finish(attempt_id,"published")
        draft_path=root.parent/"drafts"/attempt["draft_id"]/"draft.json"
        if draft_path.exists():
            draft=json.loads(draft_path.read_text())
            draft["recovered_publication_errors"]=draft.pop("publication_errors",[])
            draft.update(status="published",facebook_story=result,recovered_at=datetime.now(timezone.utc).isoformat())
            draft.setdefault("campaign_deliveries",[]).append({"target":"recovered_facebook_story","channel":"facebook_story","receipt":result})
            atomic_json(draft_path,draft)
        atomic_json(folder/(attempt_id+"_result.json"),{"status":"published","receipt":result,"original_error":error})
        return {"status":"published","receipt":result,"other_destinations_preserved":len(rows)-1}
    except Exception as exc:
        queue.finish(attempt_id,"partial",error+" | recovery: "+safe_error(exc))
        raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt",required=True)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args();s=load_settings()
    result=recover(campaign_root(s),args.attempt,InstagramGraphPublisher(s),execute=args.execute)
    print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":main()
