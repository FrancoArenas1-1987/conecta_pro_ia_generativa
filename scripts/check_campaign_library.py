"""Check approved campaign captions and media, without publishing or generating."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import imageio_ffmpeg
import numpy as np
from moviepy.editor import VideoFileClip
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from conecta_video_ai.campaign_queue import inside
from conecta_video_ai.instagram_content_engine import InstagramContentEngine
from conecta_video_ai.publication_checks import validate_caption, caption_digest, verify_public_image, verify_public_video

def check(path, *, remote=False):
    root=path.parent
    manifest=json.loads(path.read_text(encoding="utf-8-sig"))
    ids=[e["campaign_id"] for e in manifest["entries"]]
    if len(ids)!=len(set(ids)):raise ValueError("Duplicate campaign ids")
    reports=[]
    ff=imageio_ffmpeg.get_ffmpeg_exe()
    for e in manifest["entries"]:
        if not e.get("enabled"):continue
        if e.get("approval_status")!="approved":raise ValueError("Campaign is not approved")
        validate_caption(e["caption"],whatsapp_url="https://wa.me/56983434503")
        if caption_digest(e["caption"])!=e["caption_sha256"]:raise ValueError("Caption checksum changed")
        kind=e.get("media_type","video")
        files=[("video","sha256"),("cover","cover_sha256")] if kind=="video" else [("image","sha256")]
        if kind=="image" and e.get("publish_stories",True):files.append(("story_image","story_sha256"))
        report={"campaign_id":e["campaign_id"],"media_type":kind,"passed":True,"files":[]}
        for key,hashkey in files:
            p=inside(root,e[key])
            if hashlib.sha256(p.read_bytes()).hexdigest()!=e[hashkey]:raise ValueError("Media checksum changed")
            details={"file":p.name,"bytes":p.stat().st_size}
            if p.suffix.lower()==".mp4":
                qc=InstagramContentEngine._validate_ig_video(None,video_path=p,target_seconds=e["duration_seconds"],require_audio=True)
                if not qc["passed"]:raise ValueError(str(qc))
                with VideoFileClip(str(p),audio=False) as clip:
                    details.update(duration=clip.duration,size=clip.size,fps=clip.fps)
                    if clip.size!=[1080,1920] or abs(clip.fps-30)>.1:raise ValueError("Wrong video size or frame rate")
                    for t in [1,clip.duration*.35,clip.duration*.7,clip.duration-.5]:
                        if clip.get_frame(t).std()<8:raise ValueError("Blank video frame")
                decoded=subprocess.run([ff,"-v","error","-i",str(p),"-f","null","-"],capture_output=True)
                if decoded.returncode or decoded.stderr:raise ValueError("Video decode failed")
                audio=subprocess.run([ff,"-v","error","-i",str(p),"-vn","-f","f32le","-ac","1","-ar","22050","-"],capture_output=True,check=True)
                samples=np.frombuffer(audio.stdout,dtype=np.float32)
                details.update(audio_rms=float(np.sqrt(np.mean(samples**2))),audio_peak=float(np.abs(samples).max()))
                if not .005<details["audio_rms"] or details["audio_peak"]>=1:raise ValueError("Audio silent or clipping")
                data=p.read_bytes()
                if not 0<data.find(b"moov")<data.find(b"mdat"):raise ValueError("MP4 missing faststart")
                if remote:verify_public_video(e["public_video_url"],sha256=e[hashkey],size_bytes=p.stat().st_size)
            else:
                with Image.open(p) as image:
                    details.update(size=list(image.size),format=image.format)
                    ratio=image.width/image.height
                    if key in {"image","story_image"}:
                        if image.format!="JPEG" or p.stat().st_size>8_000_000:raise ValueError("Invalid JPEG")
                        if key=="image" and not .8<=ratio<=1.91:raise ValueError("Invalid feed ratio")
                        if key=="story_image" and abs(ratio-9/16)>.001:raise ValueError("Invalid Story ratio")
                    image.verify()
                if remote and key in {"image","story_image"}:
                    verify_public_image(e["public_image_url" if key=="image" else "public_story_image_url"],sha256=e[hashkey],size_bytes=p.stat().st_size)
            report["files"].append(details)
        reports.append(report)
        print(e["campaign_id"],"OK",flush=True)
    return {"summary":{"campaigns":len(reports),"images":sum(r["media_type"]=="image" for r in reports),"videos":sum(r["media_type"]=="video" for r in reports),"failures":0,"remote_bytes_checked":remote},"campaigns":reports}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--remote",action="store_true")
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    report=check(args.manifest,remote=args.remote)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["summary"]))
