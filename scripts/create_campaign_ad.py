from pathlib import Path
import sys,asyncio,json
R=Path(__file__).resolve().parents[1]; O=R/'output/video_ads/guia_siglo_xxi_v1';O.mkdir(parents=True,exist_ok=True)
S='¿Buscas un profesional para tu casa? Encuentra profesionales y servicios para tu día a día, en todo Chile. Conecta Pro I A. La guía de servicios del siglo veintiuno. Buscar contactos es gratis. Escríbenos por WhatsApp y cuéntanos qué necesitas.'
if '--voice' in sys.argv:
 import edge_tts
 async def voice(): await edge_tts.Communicate(S,voice='es-CL-CatalinaNeural',rate='+3%').save(str(O/'voz.mp3'))
 asyncio.run(voice());sys.exit()
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageOps
from moviepy.editor import VideoClip,AudioFileClip,CompositeAudioClip,concatenate_videoclips
from moviepy.audio.fx.all import audio_loop
W,H=1080,1920;G='#005D44';I='#003B2D';C='#FAF6ED';Y='#FFCF32'
def font(s,b=True):return ImageFont.truetype('C:/Windows/Fonts/'+('seguibl.ttf' if b else 'segoeui.ttf'),s)
def txt(d,p,s,n=40,c=I,b=True):d.multiline_text(p,s,font=font(n,b),fill=c,spacing=12)
def pill(d,box,s,bg=G,fg='white',n=34):
 d.rounded_rectangle(box,radius=32,fill=bg);bb=d.textbbox((0,0),s,font=font(n));d.text(((box[0]+box[2]-bb[2])/2,(box[1]+box[3]-(bb[3]-bb[1]))/2-bb[1]),s,font=font(n),fill=fg)
A=R/'output/imagegen/campana_guia'
a=Image.open(A/'01_profesional_para_tu_casa.png').convert('RGB');b=Image.open(A/'02_muchos_servicios.png').convert('RGB');c=Image.open(A/'03_guia_siglo_xxi.png').convert('RGB')
def photo(im,src,cr,box,z):
 cr=tuple(round(v*(src.width/1122 if k%2==0 else src.height/1402)) for k,v in enumerate(cr));src=src.crop(cr)
 w,h=box[2]-box[0],box[3]-box[1];p=ImageOps.fit(src,(int(w*z),int(h*z)),method=Image.Resampling.LANCZOS);x=(p.width-w)//2;y=(p.height-h)//2;p=p.crop((x,y,x+w,y+h));mask=Image.new('L',(w,h));ImageDraw.Draw(mask).rounded_rectangle((0,0,w,h),radius=46,fill=255);im.paste(p,box[:2],mask)
heads=['¿Buscas ayuda\npara tu casa?','Tu hogar.\nTu día a día.','En todo Chile.','La guía de servicios\ndel siglo XXI.','Buscar contactos\nes GRATIS.']
subs=['Encuentra a quién contactar.','Profesionales y múltiples servicios.','Un solo lugar para buscar contactos.','ConectaProIA','Cuéntanos qué necesitas.']
v=AudioFileClip(str(O/'voz.mp3')) if (O/'voz.mp3').exists() and (O/'voz.mp3').stat().st_size > 1000 else None
D=max(22,v.duration+1.8 if v else 22);lengths=[4,4,4,4,D-16]
def frame(i,t,l):
 im=Image.new('RGB',(W,H),C);d=ImageDraw.Draw(im);d.ellipse((810,-210,1320,300),fill='#DCEFE4');txt(d,(76,165),'ConectaProIA',53);d.rounded_rectangle((77,248,210,255),radius=3,fill=G)
 ease=1-(1-min(1,t/.65))**3;txt(d,(78,int(335+26*(1-ease))),heads[i],68 if i==3 else 76);txt(d,(80,560),subs[i],34,b=False);z=1+min(1,t/l)*.045
 if i==0:photo(im,a,(20,720,1100,1210),(65,690,1015,1410),z)
 elif i in (1,2):
  boxes=[(65,650,530,1040),(550,650,1015,1040),(65,1060,530,1450),(550,1060,1015,1450)];crops=[(55,470,550,830),(580,470,1090,830),(40,850,550,1180),(580,850,1090,1180)]
  for box,cr in zip(boxes,crops):photo(im,b,cr,box,z)
 elif i==3:photo(im,c,(0,470,1122,1115),(65,680,1015,1440),z)
 else:
  d.rounded_rectangle((65,720,1015,1400),radius=48,fill=G);txt(d,(120,790),'Profesionales.\nServicios.\nContactos.',77,'white');pill(d,(120,1170,960,1300),'BÚSQUEDA SIN COSTO',Y,I,39)
 d=ImageDraw.Draw(im)
 if i<4:pill(d,(75,1510,1005,1625),'BUSCAR CONTACTOS ES GRATIS');txt(d,(80,1670),'Profesionales y servicios en todo Chile.',33,b=False)
 else:pill(d,(75,1500,1005,1625),'ESCRÍBENOS POR WHATSAPP',Y,I,37);txt(d,(80,1660),'conectaproia.cl',49)
 txt(d,(80,1750),'El servicio contratado lo cobra cada profesional.',27,b=False)
 for k in range(5):d.rounded_rectangle((80+k*185,1830,245+k*185,1837),radius=3,fill=G if k<=i else '#CFDCD5')
 return np.asarray(im)
clips=[]
for i,l in enumerate(lengths):
 clips.append(VideoClip(lambda t,i=i,l=l:frame(i,t,l),duration=l));Image.fromarray(frame(i,1,l)).save(O/f'escena_{i+1:02}.jpg',quality=92)
video=concatenate_videoclips(clips,method='chain');m=AudioFileClip(str(R/'config/music/story/mixkit-corporate-drive-493.mp3'));bed=audio_loop(m,duration=D).volumex(.12 if v else .45).audio_fadein(.6).audio_fadeout(1.5);tracks=[bed]
if v:tracks.append(v.volumex(1.1).set_start(.55))
video=video.set_audio(CompositeAudioClip(tracks)).fadein(.2).fadeout(.45)
video.write_videofile(str(O/'conectaproia_publicitario_v1.mp4'),fps=30,codec='libx264',audio_codec='aac',audio_bitrate='192k',bitrate='6000k',preset='fast',threads=4,ffmpeg_params=['-movflags','+faststart','-pix_fmt','yuv420p'],logger=None)
meta={'duration_seconds':D,'resolution':[W,H],'fps':30,'voice':'es-CL-CatalinaNeural' if v else None,'script':S,'music':'mixkit-corporate-drive-493.mp3 (biblioteca existente)','published':False};(O/'ficha.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(meta,ensure_ascii=False));video.close();m.close()
if v:v.close()

