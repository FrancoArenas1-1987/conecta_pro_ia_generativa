"""Read-only campaign rotation status, without contacting providers."""
from pathlib import Path
import json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from conecta_video_ai.settings import load_settings
from conecta_video_ai.campaign_queue import campaign_root
from conecta_video_ai.publication_checks import caption_digest
s=load_settings();r=campaign_root(s);p=r/'manifest.json';result={'manifest_exists':p.exists(),'quality_gate_enabled':s.instagram_publish_quality_gate_enabled,'carousel_requires_review':(Path(s.output_root)/'instagram/carousel_pending.json').exists()}
if p.exists():
 m=json.loads(p.read_text(encoding='utf-8-sig'));result.update(enabled=bool(m.get('enabled')),min_interval_hours=m.get('min_interval_hours'),repeat_after_days=m.get('repeat_after_days'),campaigns=[{'campaign_id':c['campaign_id'],'enabled':c.get('enabled'),'approval_status':c.get('approval_status'),'caption_hash_matches':caption_digest(c.get('caption',''))==c.get('caption_sha256')} for c in m.get('entries',[])])
 p=r/'queue.sqlite3'
 if p.exists():
  with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:
   db.row_factory=sqlite3.Row
   result['last_slot_kind']=dict(db.execute('SELECT key,value FROM controls').fetchall()).get('last_slot_kind')
   result['recent_attempts']=[dict(row) for row in db.execute('SELECT campaign,draft_id,started_at,status,finished_at,error FROM attempts ORDER BY started_at DESC LIMIT 10')]
   result['delivery_statuses']=[dict(row) for row in db.execute('SELECT channel,status,count(*) AS count FROM deliveries GROUP BY channel,status')]
print(json.dumps(result,ensure_ascii=False,indent=2))
