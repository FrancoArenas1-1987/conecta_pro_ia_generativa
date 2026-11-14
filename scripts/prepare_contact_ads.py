"""Prepare delivery formats and tracked captions from built-in-generated originals.
No AI API calls and no publishing. Approval remains a separate editorial step.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import imageio_ffmpeg
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from conecta_video_ai.acquisition_tracking import tracked_whatsapp_url,tracking_code_for
from conecta_video_ai.publication_checks import FREE_SEARCH,DISCLAIMER,validate_caption,caption_digest
from create_fresh_ads import gallery

CONTACT="https://wa.me/56983434503"
DEFAULT_OUT=ROOT/"output/advertising/contacto_2026_11_13"
BACKGROUNDS={
 "gotera_hogar_20261113_v1":"F6F4E9",
 "tu_comuna_contacto_20261113_v1":"103E37",
 "documento_traduccion_20261113_v1":"FFF6E9",
 "pizza_compartir_20261113_v1":"FFF6E9",
}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def delivery(source,target,*,story,background):
    width,height=(1080,1920) if story else (1080,1350)
    # Encoding/fit only. Preserve the entire approved artwork and its contact text.
    filters=(f"scale=1080:1350:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x{background},setsar=1")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-v","error","-i",str(source),
        "-vf",filters,"-frames:v","1","-q:v","2",str(target)],check=True)
    with Image.open(target) as image:
        if image.format!="JPEG" or image.size!=(width,height):
            raise ValueError("Invalid delivery format")
        image.verify()

def prepare(folder, spec_path=None):
    specs=json.loads(Path(spec_path or ROOT/"config/campaigns.contacto.prompts.json").read_text(encoding="utf-8"))["entries"]
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    entries=[]
    for spec in specs:
        code=spec["id"];source=folder/(code+".png")
        if not source.is_file():raise FileNotFoundError("Copy the built-in image output first: "+str(source))
        with Image.open(source) as image:image.verify()
        reference=tracking_code_for("campaign:"+code)
        url=tracked_whatsapp_url(CONTACT,reference,spec["service"])
        caption=(spec["intro"]+"\n\n"+FREE_SEARCH+
            "\n\n"+spec["cta"]+"\nWhatsApp: "+url+
            "\nWeb: https://conectaproia.cl\n\n"+DISCLAIMER+"\n\n#ConectaProIA #Servicios #Chile")
        validate_caption(caption,whatsapp_url=CONTACT)
        feed=folder/(code+"_feed.jpg");story=folder/(code+"_story.jpg")
        delivery(source,feed,story=False,background=spec.get("background") or BACKGROUNDS[code])
        delivery(source,story,story=True,background=spec.get("background") or BACKGROUNDS[code])
        entries.append({"campaign_id":code,"title":spec["title"],"angle":spec["angle"],
          "objective":"captar_clientes","caption":caption,"caption_sha256":caption_digest(caption),
          "tracking_code":reference,"media_type":"image","image":feed.name,"sha256":digest(feed),
          "story_image":story.name,"story_sha256":digest(story),"publish_stories":True,
          "approval_status":"pending_review","enabled":False,"repeat_after_days":21,
          "public_image_url":"https://conectaproia.cl/campanas/"+digest(feed)[:20]+".jpg",
          "public_story_image_url":"https://conectaproia.cl/campanas/"+digest(story)[:20]+".jpg",
          "source_file":source.name,"source_sha256":digest(source)})
        (folder/(code+"_caption.txt")).write_text(caption,encoding="utf-8")
    manifest={"schema_version":2,"enabled":False,"min_interval_hours":24,"repeat_after_days":21,"entries":entries}
    (folder/"manifest.review.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    gallery(entries,folder/"revisar.html")
    print(json.dumps({"pieces":len(entries),"delivery_images":len(entries)*2,"approval":"pending_review","folder":str(folder)},ensure_ascii=False))
    return manifest

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=DEFAULT_OUT)
    parser.add_argument("--specs",type=Path,help="Campaign descriptions and source prompts")
    args=parser.parse_args();prepare(args.output,args.specs)
