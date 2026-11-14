"""Render three original motion-design Reels offline. Never publishes or calls an AI API."""
from __future__ import annotations
import argparse
from functools import lru_cache
import hashlib,json,math,subprocess,sys,wave
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from moviepy.editor import VideoClip,AudioFileClip
import imageio_ffmpeg
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from conecta_video_ai.acquisition_tracking import tracking_code_for,tracked_whatsapp_url
from conecta_video_ai.publication_checks import FREE_SEARCH,DISCLAIMER,caption_digest,validate_caption
from create_fresh_ads import gallery,normalize_video_music

W,H=1080,1920
SAFE=(90,290,990,1240)
CONTACT="https://wa.me/56983434503"
DEFAULT=ROOT/"output/advertising/reels_2026_11_14"
RESAMPLE=Image.Resampling.LANCZOS

@lru_cache(maxsize=64)
def font(size,bold=True):
    paths=[Path("C:/Windows/Fonts")/("seguibl.ttf" if bold else "segoeui.ttf"),
           Path("/usr/share/fonts/truetype/dejavu")/("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    for path in paths:
        if path.exists():return ImageFont.truetype(str(path),size)
    raise RuntimeError("A supported font is required")

@lru_cache(maxsize=512)
def label(text,size,color,width=850,height=190,bold=True):
    for n in range(size,21,-1):
        f=font(n,bold);draw=ImageDraw.Draw(Image.new("RGBA",(1,1)))
        box=draw.multiline_textbbox((0,0),text,font=f,spacing=8)
        tw,th=box[2]-box[0],box[3]-box[1]
        if tw+4<=width and th+4<=height:
            layer=Image.new("RGBA",(tw+4,th+4))
            ImageDraw.Draw(layer).multiline_text((2-box[0],2-box[1]),text,font=f,fill=color,spacing=8)
            return layer,n
    raise ValueError("Copy does not fit: "+text)

def ease(value):
    value=max(0,min(1,value));return 1-(1-value)**3

def alpha(layer,opacity):
    out=layer.copy();out.putalpha(out.getchannel("A").point(lambda v:round(v*max(0,min(1,opacity)))))
    return out

class Renderer:
    def __init__(self,spec,folder):
        self.spec,self.folder=spec,folder
        self.bg,self.ink,self.accent=spec["palette"]
        self.boxes=set();self.photo=None
        self.base=Image.new("RGBA",(W,H),self.bg)
        d=ImageDraw.Draw(self.base)
        # Background movement is decorative; no important copy is below the safe region.
        for y in range(1350,2100,160):
            d.arc((-420,y-120,1540,y+460),0,360,fill=self.accent,width=2)
        d.ellipse((820,-180,1360,360),fill=self.accent)
        if spec["style"]=="pet_editorial":
            photo=Image.open(folder/"peluqueria_canina_escena.png").convert("RGBA")
            self.photo=photo.resize((W,H),RESAMPLE)
            # Video-only overlay keeps type legible without changing the source asset.
            a=np.zeros((H,W),dtype=np.uint8)
            for y in range(H):
                a[y,:]=round(110*(1-y/750)) if y<750 else round(min(190,max(0,(y-930)*.85)))
            overlay=Image.new("RGBA",(W,H),self.bg)
            overlay.putalpha(Image.fromarray(a));self.overlay=overlay

    def put(self,frame,text,x,y,*,size=36,color=None,width=850,height=190,bold=True,opacity=1):
        layer,n=label(text,size,color or self.ink,width,height,bold)
        box=(round(x),round(y),round(x)+layer.width,round(y)+layer.height)
        if not(SAFE[0]<=box[0] and SAFE[1]<=box[1] and box[2]<=SAFE[2] and box[3]<=SAFE[3]):
            raise ValueError("Important text outside safe zone: "+text+" "+str(box))
        self.boxes.add((text,*box,n))
        frame.alpha_composite(layer if opacity>=1 else alpha(layer,opacity),(round(x),round(y)))

    def card(self,frame,box,fill,outline=None):
        x,y,x2,y2=box
        shadow=Image.new("RGBA",frame.size)
        ImageDraw.Draw(shadow).rounded_rectangle((x,y+5,x2,y2+5),radius=24,fill=(0,0,0,23))
        frame.alpha_composite(shadow)
        ImageDraw.Draw(frame).rounded_rectangle(box,radius=24,fill=fill,outline=outline,width=2)

    def frame(self,t):
        s=self.spec
        if self.photo is not None:
            out=Image.new("RGBA",(W,H),self.bg)
            # A slow editorial camera move within this video, keeping the dog's face visible.
            shift=round(72+12*math.sin(t*.35))
            zoom=1+.025*t/s["duration"]
            photo=self.photo.resize((round(W*zoom),round(H*zoom)),RESAMPLE)
            out.alpha_composite(photo,(-round((photo.width-W)/2),shift))
            out.alpha_composite(self.overlay)
        else:
            out=self.base.copy()
            d=ImageDraw.Draw(out)
            cx=600+round(100*math.sin(t*.55))
            d.ellipse((cx,1460,cx+460,1920),outline=self.accent,width=3)
        phase=min(next((i for i,v in enumerate(s["phases"][1:]) if t<v),len(s["headlines"])-1),len(s["headlines"])-1)
        local=t-s["phases"][phase];entrance=ease(local/.35)
        self.put(out,"ConectaProIA",96,306,size=44,height=62)
        self.put(out,s["eyebrow"],96,386,size=26,height=42)
        d=ImageDraw.Draw(out)
        d.rounded_rectangle((96,371,976,375),radius=2,fill=self.accent)
        d.ellipse((96+round(868*t/s["duration"]),366,108+round(868*t/s["duration"]),379),fill=self.ink)
        self.put(out,s["headlines"][phase],96,452+round(10*(1-entrance)),size=82,height=184,opacity=.45+.55*entrance)
        self.put(out,s["body"][phase],96,650,size=32,height=70,bold=False)

        if s["style"]=="animated_message":
            if phase==0:
                self.card(out,(110,745,938,908),self.accent)
                self.put(out,"¿Qué servicio necesitas?",145,788,size=46,color=self.ink,width=740,height=75)
            elif phase==1:
                self.card(out,(110,735,938,918),self.ink)
                message="Busco gasfitería.\nMi comuna es..."
                count=max(1,min(len(message),int((local+.08)*19)))
                self.put(out,message[:count],145,763,size=43,color=self.bg,width=742,height=125)
                # The example is a user's message, never a fabricated platform response.
                d=ImageDraw.Draw(out);d.ellipse((865,843,906,884),fill=self.accent)
                d.line((876,862,893,862),fill=self.ink,width=4);d.line((887,855,894,862,887,870),fill=self.ink,width=3)
            else:
                self.card(out,(110,745,938,908),self.accent)
                self.put(out,"NECESIDAD  +  COMUNA",142,798,size=43,color=self.ink,width=760,height=65)
        elif s["style"]=="kinetic_checklist":
            for i,text in enumerate(["Gasfitería","Electricidad","Mudanzas"]):
                lag=max(0,local-i*.10);x=110+round(20*(1-ease(lag/.4)));y=726+i*66
                active=phase==1 and i==int(local/.8)%3
                fill=self.accent if active else self.ink if phase==len(s["headlines"])-1 else self.bg
                self.card(out,(x,y,x+806,y+57),fill,outline=self.accent)
                color=self.bg if phase==len(s["headlines"])-1 else self.bg if active else self.ink
                d=ImageDraw.Draw(out);d.ellipse((x+19,y+17,x+41,y+39),outline=self.accent,width=3)
                self.put(out,text,x+60,y+9,size=34,color=color,width=680,height=42)
        # Contact and price distinction persist through the full video, inside Reels safe area.
        self.put(out,"Buscar contactos es gratis.",96,951,size=33,height=49)
        self.card(out,(96,1014,976,1100),self.ink if self.photo is None else "#FFF6E8")
        self.put(out,"WhatsApp  +56 9 8343 4503",121,1034,size=47,color=self.bg if self.photo is None else self.bg,width=833,height=64)
        self.put(out,"conectaproia.cl",96,1120,size=35,height=55,bold=False)
        self.put(out,"El servicio lo cobra cada profesional.",96,1194,size=24,width=745,height=36,bold=False)
        return np.asarray(out.convert("RGB"))

def original_audio(path,duration,seed):
    """A restrained original pluck/percussion bed synthesized locally at 48 kHz."""
    sr=48000;n=round(sr*duration);mix=np.zeros(n,dtype=np.float64)
    rng=np.random.default_rng(seed);beat=.6
    def add(start,sound):
        a=round(start*sr)
        if a<0 or a>=n:return
        end=min(n,a+len(sound));mix[a:end]+=sound[:end-a]
    for i,start in enumerate(np.arange(0,duration,beat)):
        t=np.arange(round(sr*.22))/sr
        kick=.14*np.sin(2*np.pi*(54*t+5*(1-np.exp(-t*28))))*np.exp(-t*23);add(start,kick)
        t=np.arange(round(sr*.045))/sr
        add(start+.3,.015*rng.normal(size=len(t))*np.exp(-t*100))
    progression=[[52,55,59],[48,52,55],[55,59,62],[50,54,57]]
    for i,start in enumerate(np.arange(.08,duration,.3)):
        midi=progression[(i//8)%4][i%3]+12;freq=440*2**((midi-69)/12)
        t=np.arange(round(sr*.7))/sr;env=np.exp(-t*6)*(1-np.exp(-t*110))
        sound=.065*(np.sin(2*np.pi*freq*t)+.25*np.sin(4*np.pi*freq*t))*env;add(start,sound)
    # Soft, original rising transition ticks highlight the scene changes.
    for start in [2.0,7.5,10.5]:
        if start>=duration:continue
        t=np.arange(round(sr*.13))/sr;add(start,.035*np.sin(2*np.pi*(670*t+320*t*t))*np.exp(-t*28))
    timeline=np.arange(n)/sr;mix*=np.minimum(1,timeline/.3)*np.minimum(1,(duration-timeline)/.65)
    mix*=.65/max(.65,float(np.abs(mix).max()))
    stereo=np.column_stack([mix,np.roll(mix,11)*.97]);pcm=(np.clip(stereo,-.95,.95)*32767).astype("<i2")
    with wave.open(str(path),"wb") as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def build(folder,*,stills_only=False):
    config=json.loads((ROOT/"config/campaigns.reels_20261114.json").read_text(encoding="utf-8"))
    folder.mkdir(parents=True,exist_ok=True);entries=[]
    for index,s in enumerate(config["entries"]):
        renderer=Renderer(s,folder);code=s["id"];duration=s["duration"]
        for phase,start in enumerate(s["phases"][:-1]):
            Image.fromarray(renderer.frame(start+.7)).save(folder/(code+f"_scene_{phase+1}.jpg"),quality=93)
        cover=folder/(code+"_cover.jpg");Image.fromarray(renderer.frame(1.2)).save(cover,quality=94)
        if stills_only:continue
        wav=folder/(code+"_original_audio.wav");original_audio(wav,duration,31+index)
        sound=AudioFileClip(str(wav));clip=VideoClip(renderer.frame,duration=duration).set_audio(sound)
        video=folder/(code+".mp4")
        clip.write_videofile(str(video),fps=30,codec="libx264",audio_codec="aac",audio_fps=48000,
            audio_bitrate="192k",bitrate="4800k",preset="veryfast",threads=4,
            temp_audiofile=str(folder/(code+"_temp.m4a")),logger=None,
            ffmpeg_params=["-pix_fmt","yuv420p","-g","60","-keyint_min","60","-sc_threshold","0","-movflags","+faststart","-use_editlist","0"])
        clip.close();sound.close();normalize_video_music(video,duration)
        reference=tracking_code_for("campaign:"+code)
        url=tracked_whatsapp_url(CONTACT,reference,s["service"])
        caption=s["intro"]+"\n\n"+FREE_SEARCH+"\n\n"+s["cta"]+"\nWhatsApp: "+url+"\nWeb: https://conectaproia.cl\n\n"+DISCLAIMER+"\n\n#ConectaProIA #Servicios #Chile"
        validate_caption(caption,whatsapp_url=CONTACT)
        e={"campaign_id":code,"title":s["title"],"angle":s["style"],"objective":"captar_clientes",
           "media_type":"video","video":video.name,"cover":cover.name,"duration_seconds":duration,
           "sha256":sha(video),"cover_sha256":sha(cover),"caption":caption,"caption_sha256":caption_digest(caption),
           "tracking_code":reference,"approval_status":"pending_review","enabled":False,"repeat_after_days":21,
           "publish_stories":True,"audio":"original_locally_synthesized","public_video_url":"https://conectaproia.cl/campanas/"+sha(video)[:20]+".mp4"}
        entries.append(e);(folder/(code+"_caption.txt")).write_text(caption,encoding="utf-8")
        (folder/(code+"_layout.json")).write_text(json.dumps({"safe_rectangle":SAFE,"all_rendered_text_checked":True,"text_boxes":[list(b) for b in sorted(renderer.boxes)]},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"rendered":code,"seconds":duration,"safe_zone":"passed"}),flush=True)
    if not stills_only:
        manifest={"schema_version":2,"enabled":False,"min_interval_hours":24,"repeat_after_days":21,"entries":entries}
        (folder/"manifest.review.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        gallery(entries,folder/"revisar.html")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,default=DEFAULT);parser.add_argument("--stills-only",action="store_true")
    args=parser.parse_args();build(args.output,stills_only=args.stills_only)
