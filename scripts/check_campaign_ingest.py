"""Check Instagram ingestion of approved campaigns. Creates unpublished containers only."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from conecta_video_ai.instagram_graph_publisher import InstagramGraphPublisher
from conecta_video_ai.settings import load_settings
from check_campaign_library import check

class IngestOnlyPublisher(InstagramGraphPublisher):
    def _http(self,*,method,path,params,access_token=None):
        allowed=(method.upper()=="POST" and path==f"/{self.ig_user_id}/media") or method.upper()=="GET"
        if not allowed:raise RuntimeError("Only unpublished Instagram containers and status reads are allowed")
        return super()._http(method=method,path=path,params=params,access_token=access_token)

    def publish_media_container(self,**kwargs):
        raise RuntimeError("Publishing is forbidden in an ingestion check")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    check(args.manifest,remote=True)
    publisher=IngestOnlyPublisher(load_settings())
    manifest=json.loads(args.manifest.read_text(encoding="utf-8-sig"));rows=[]
    for item in manifest["entries"]:
        if not item.get("enabled") or item.get("approval_status")!="approved":continue
        kind=item.get("media_type","video")
        formats=["REELS","STORIES"] if kind=="video" else ["FEED","STORIES"]
        for fmt in formats:
            if fmt=="STORIES" and not item.get("publish_stories",True):continue
            if kind=="video":
                creation=publisher.create_video_container(video_url=item["public_video_url"],
                    caption=item["caption"] if fmt=="REELS" else "",media_type=fmt,share_to_feed=fmt=="REELS")
            else:
                creation=publisher.create_media_container(
                    image_url=item["public_story_image_url"] if fmt=="STORIES" else item["public_image_url"],
                    caption=item["caption"] if fmt=="FEED" else "",media_type="STORIES" if fmt=="STORIES" else None)
            state=publisher.wait_until_container_ready(creation_id=creation,max_wait_seconds=45)
            status=str(state.get("status_code") or state.get("status"))
            rows.append({"campaign_id":item["campaign_id"],"format":fmt,"creation_id":creation,"status":status})
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps({"published":False,"containers":rows},indent=2),encoding="utf-8")
            print(json.dumps({"campaign":item["campaign_id"],"format":fmt,"status":status,"published":False}),flush=True)

if __name__=="__main__":main()
