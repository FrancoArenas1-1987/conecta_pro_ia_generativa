"""Collect actual Meta metrics. No publishing, paid AI calls or ad purchases."""
from pathlib import Path
import argparse,json,sys
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from conecta_video_ai.settings import load_settings
from conecta_video_ai.instagram_graph_publisher import InstagramGraphPublisher
from conecta_video_ai.social_analytics import (MetaInsightsCollector,analyze,save_observations,
    latest_observations,parse_time,stamp,write_report_html)
from conecta_video_ai.campaign_queue import atomic_json,safe_error
from conecta_video_ai.acquisition_tracking import whatsapp_enquiries

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-posts",type=int,default=50)
    parser.add_argument("--max-calls",type=int,default=120)
    parser.add_argument("--force",action="store_true")
    args=parser.parse_args()
    s=load_settings();folder=Path(s.output_root)/"instagram/analytics";folder.mkdir(parents=True,exist_ok=True)
    old=folder/"latest.json"
    if old.exists() and not args.force:
        try:
            at=parse_time(json.loads(old.read_text())["collected_at"])
            if at and stamp()-at<timedelta(hours=4):
                print(json.dumps({"ok":True,"skipped":True,"reason":"insights_collected_recently"}));return 0
        except (ValueError,KeyError):pass
    try:
        report=MetaInsightsCollector(InstagramGraphPublisher(s),s.output_root,max_calls=args.max_calls,max_posts=args.max_posts).collect()
        if not report["records"] or not any("reach" in r.get("metrics",{}) for r in report["records"]):
            atomic_json(folder/"last_error.json",{"at":stamp().isoformat(),"warnings":report["warnings"],"error":"no_insights_available"})
            print(json.dumps({"ok":False,"reason":"no_insights_available"}));return 1
        save_observations(folder,report)
        historical=latest_observations(folder)
        report["whatsapp_attribution"]=whatsapp_enquiries(historical)
        atomic_json(folder/"latest.json",report)
        result=analyze(historical)
        atomic_json(folder/"analysis.json",result)
        atomic_json(folder/"policy.json",result["policy"])
        write_report_html(folder/"informe.html",result,report)
        summary={"ok":True,"records_collected":len(report["records"]),"records_in_history":len(historical),
                 "with_reach":sum("reach" in r["metrics"] for r in report["records"]),
                 "with_unavailable_metrics":sum(bool(r["issues"]) for r in report["records"]),
                 "api_reads":report["api_reads"],"automatic_category_weights":result["policy"]["category_weights"]}
        atomic_json(folder/"summary.json",summary)
        print(json.dumps(summary,ensure_ascii=False));return 0
    except Exception as exc:
        atomic_json(folder/"last_error.json",{"at":stamp().isoformat(),"error":safe_error(exc)})
        print(json.dumps({"ok":False,"reason":safe_error(exc)}));return 1

if __name__=="__main__":raise SystemExit(main())
