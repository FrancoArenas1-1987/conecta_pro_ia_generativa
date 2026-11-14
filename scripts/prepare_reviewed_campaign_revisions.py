"""Prepare versioned campaign revisions from built-in image outputs. Never publishes."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from prepare_contact_ads import delivery,digest
from conecta_video_ai.publication_checks import validate_caption,caption_digest
from create_fresh_ads import gallery


def checked_source(folder,name):
    if Path(name).name!=name:raise ValueError("Source must be a filename inside the review folder")
    path=folder/name
    if not path.is_file():raise FileNotFoundError(name)
    return path


def prepare(library,specs,folder):
    folder=Path(folder);original=json.loads(Path(library).read_text(encoding="utf-8"))
    byid={e["campaign_id"]:e for e in original["entries"]};entries=[];previews=[]
    for spec in json.loads(Path(specs).read_text(encoding="utf-8"))["entries"]:
        identifier=spec["id"];entry=dict(byid[identifier]);old={k:entry[k] for k in ["image","sha256","story_image","story_sha256","source_file","source_sha256","source_story_file","source_story_sha256","public_image_url","public_story_image_url"] if k in entry}
        entry["previous_media"]=list(entry.get("previous_media") or [])
        if spec.get("feed_source"):
            source=checked_source(folder,spec["feed_source"]);feed=folder/(identifier+"_feed_contacto_v2.jpg")
            delivery(source,feed,story=False,background="FFF7EE")
            entry.update(image=feed.name,sha256=digest(feed),source_file=source.name,source_sha256=digest(source))
        story_source=checked_source(folder,spec["story_source"]);story=folder/(identifier+"_story_native_v2.jpg")
        delivery(story_source,story,story=True,background="FFF7EE",native_story=True)
        entry.update(story_image=story.name,story_sha256=digest(story),publish_stories=True,story_design="native",source_story_file=story_source.name,source_story_sha256=digest(story_source))
        if spec.get("caption"):entry["caption"]=spec["caption"]
        validate_caption(entry["caption"],whatsapp_url="https://wa.me/56983434503")
        entry.update(caption_sha256=caption_digest(entry["caption"]),approval_status="pending_review",enabled=False,revision_reason=spec["reason"])
        entry["public_image_url"]="https://conectaproia.cl/campanas/"+entry["sha256"][:20]+".jpg"
        entry["public_story_image_url"]="https://conectaproia.cl/campanas/"+entry["story_sha256"][:20]+".jpg"
        current={k:entry.get(k) for k in old}
        if current!=old and old not in entry["previous_media"]:entry["previous_media"].append(old)
        (folder/(identifier+"_caption.txt")).write_text(entry["caption"],encoding="utf-8")
        entries.append(entry)
        for kind in ["image","story_image"]:
            preview={**entry,"title":entry["title"]+(" · Feed" if kind=="image" else " · Story 9:16"),"image":entry[kind]};preview.pop("story_image",None);previews.append(preview)
    result={**original,"enabled":False,"entries":entries}
    (folder/"manifest.review.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    gallery(previews,folder/"revisar.html")
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--library",type=Path,required=True);parser.add_argument("--specs",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    result=prepare(args.library,args.specs,args.output);print(json.dumps({"revised_campaigns":len(result["entries"]),"approval":"pending_review"}))
