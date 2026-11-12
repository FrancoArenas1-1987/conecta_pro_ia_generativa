"""Build campaign previews from verified production images. Never publishes."""
from pathlib import Path
from functools import lru_cache
import json,hashlib,subprocess
from PIL import Image,ImageDraw,ImageFont,ImageOps
import imageio_ffmpeg
R=Path(__file__).resolve().parents[1]
O=R/'output/video_ads/biblioteca_2026_11_12';S=O/'fuentes_aprobadas';FF=imageio_ffmpeg.get_ffmpeg_exe()
G='#005D44';INK='#003B2D';BG='#FAF6ED';Y='#FFCF32';W,H=1080,1920
@lru_cache
def font(n,b=True):return ImageFont.truetype('C:/Windows/Fonts/'+('seguibl.ttf' if b else 'segoeui.ttf'),n)
def text(d,xy,s,n=50,fill=INK,b=True):d.multiline_text(xy,s,font=font(n,b),fill=fill,spacing=8)
def pill(d,box,s):
 d.rounded_rectangle(box,radius=26,fill=Y);bb=d.textbbox((0,0),s,font=font(36));d.text(((box[0]+box[2]-bb[2])/2,box[1]+28),s,font=font(36),fill=INK)
def pic(im,name,box):
 p=Image.open(S/name).convert('RGB');p=p.crop((int(p.width*.57),int(p.height*.035),int(p.width*.99),int(p.height*.68)));w,h=box[2]-box[0],box[3]-box[1];p=ImageOps.fit(p,(w,h),method=Image.Resampling.LANCZOS);mask=Image.new('L',(w,h));ImageDraw.Draw(mask).rounded_rectangle((0,0,w,h),radius=38,fill=255);im.paste(p,box[:2],mask)
campaigns=[
 {'id':'hogar_sin_vueltas_v1','title':'Tu casa necesita ayuda','music':'mixkit-corporate-drive-493.mp3','category':'general','services':['electricidad','gasfiteria','fletes_mudanzas'],'caption':'¿Electricidad, gasfitería o una mudanza? Busca contactos de profesionales y servicios con ConectaProIA. Buscar contactos es gratis. Cuéntanos qué necesitas por WhatsApp: https://wa.me/56983434503 . La disponibilidad se confirma con cada profesional. El servicio contratado lo cobra cada profesional. #ConectaProIA #ServiciosParaElHogar #Chile',
 'scenes':[
 ('¿Tu casa necesita\nuna mano?','Encuentra a quién contactar.',['electricidad_01.png','gasfiteria_01.png']),
 ('¿Un problema\neléctrico?','Busca contactos de electricistas.',['electricidad_01.png']),
 ('¿Necesitas\nun gasfíter?','Encuentra opciones para tu hogar.',['gasfiteria_01.png']),
 ('¿Te cambias\nde casa?','Busca contactos de fletes y mudanzas.',['fletes_mudanzas_01.png']),
 ('Buscar contactos\nes GRATIS.','Tú nos cuentas. Nosotros te conectamos.',[])]},
 {'id':'mascotas_bien_cuidadas_v1','title':'También para quienes más quieres','music':'mixkit-upbeat-groove-897.mp3','category':'general','services':['medico_veterinario','peluqueria_canina'],'caption':'También hay servicios para quienes más quieres. Busca contactos de veterinaria y peluquería canina con ConectaProIA. Encontrar contactos no tiene costo. WhatsApp: https://wa.me/56983434503 . Consulta disponibilidad y valores directamente con cada profesional. #ConectaProIA #Mascotas #Veterinaria #PeluqueriaCanina',
 'scenes':[
 ('Para quienes\nmás quieres.','Encuentra servicios para tus mascotas.',['medico_veterinario_01.png','peluqueria_canina_01.png']),
 ('¿Buscas\nveterinario?','Encuentra a quién contactar.',['medico_veterinario_01.png']),
 ('¿Peluquería\ncanina?','Busca opciones para su cuidado.',['peluqueria_canina_01.png']),
 ('Encontrar contactos\nno te cuesta nada.','ConectaProIA · Profesionales y servicios.',[])]}
]
for cp in campaigns:
 out=O/cp['id'];out.mkdir(exist_ok=True);frames=[]
 for idx,(head,sub,images) in enumerate(cp['scenes']):
  im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im);d.ellipse((820,-180,1400,380),fill='#DFEEE3');text(d,(85,235),'ConectaProIA',52);d.rounded_rectangle((85,325,228,332),radius=3,fill=G);text(d,(85,395),head,68 if len(head)>31 else 76);text(d,(87,602),sub,31,b=False)
  if len(images)==2:
   for k,name in enumerate(images):pic(im,name,(85+k*465,720,525+k*465,1280))
  elif images:pic(im,images[0],(85,705,995,1280))
  else:
   d.rounded_rectangle((85,740,995,1250),radius=40,fill=G);text(d,(140,815),'Profesionales.\nServicios.\nContactos.',76,'white');text(d,(140,1160),'Un solo lugar para buscar.',36,'white',False)
  d=ImageDraw.Draw(im);pill(d,(85,1350,995,1460),'BUSCA GRATIS POR WHATSAPP');text(d,(110,1500),'+56 9 8343 4503',57);text(d,(110,1584),'conectaproia.cl',38,b=False);text(d,(110,1650),'El servicio contratado lo cobra\ncada profesional.',29,b=False)
  for j in range(len(cp['scenes'])):d.rounded_rectangle((85+j*180,1750,240+j*180,1758),radius=4,fill=G if j<=idx else '#D5E1D9')
  p=out/f'escena_{idx+1:02}.png';im.save(p);frames.append(p)
 # Encode with conservative settings from Meta's Reels specifications.
 cmd=[FF,'-y','-v','error'];dur=4;total=dur*len(frames)
 for p in frames:cmd+=['-loop','1','-framerate','30','-t',str(dur),'-i',str(p)]
 cmd+=['-stream_loop','-1','-i',str(R/'config/music/story'/cp['music'])]
 filters=[]
 for i in range(len(frames)):
  filters.append(f'[{i}:v]scale=1120:1992,zoompan=z=1+0.018*on/120:x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:d=1:s=1080x1920:fps=30,trim=duration={dur},setpts=PTS-STARTPTS[v{i}]')
 filters.append(''.join(f'[v{i}]' for i in range(len(frames)))+f'concat=n={len(frames)}:v=1:a=0[v]')
 filters.append(f'[{len(frames)}:a]atrim=duration={total},asetpts=PTS-STARTPTS,volume=0.42,afade=t=in:d=0.3,afade=t=out:st={total-1.2}:d=1.2,alimiter=limit=0.89[a]')
 target=out/(cp['id']+'.mp4')
 cmd+=['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-t',str(total),'-c:v','libx264','-preset','veryfast','-threads','4','-b:v','6M','-maxrate','10M','-bufsize','12M','-g','60','-keyint_min','60','-sc_threshold','0','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-b:a','192k','-movflags','+faststart','-use_editlist','0',str(target)]
 subprocess.run(cmd,check=True)
 meta={k:v for k,v in cp.items() if k!='scenes'};meta.update(duration_seconds=total,resolution=[W,H],fps=30,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),approval_status='pending_review',published=False,scheduled=False)
 (out/'ficha.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8');(out/'caption.txt').write_text(cp['caption'],encoding='utf-8');print(cp['id'],'ready',flush=True)
