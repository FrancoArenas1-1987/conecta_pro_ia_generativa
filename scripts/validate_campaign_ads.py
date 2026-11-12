"""Offline media and existing-publisher preflight. Makes no external requests."""
from pathlib import Path
import sys,json,subprocess,re,hashlib
import imageio_ffmpeg
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from conecta_video_ai.instagram_content_engine import InstagramContentEngine
from moviepy.editor import VideoFileClip
import numpy as np
O=R/'output/video_ads/biblioteca_2026_11_12';F=imageio_ffmpeg.get_ffmpeg_exe();reports=[]
paths=[R/'output/video_ads/guia_siglo_xxi_v1/conectaproia_publicitario_v1.mp4']+sorted(O.glob('*/*.mp4'))
for p in paths:
 with VideoFileClip(str(p),audio=False) as v:
  duration=v.duration;size=v.size;fps=v.fps
  for t in [1,duration*.35,duration*.7,duration-.5]:assert v.get_frame(t).std()>8
 meta=subprocess.run([F,'-hide_banner','-i',str(p)],capture_output=True,text=True).stderr
 audio=subprocess.run([F,'-v','error','-i',str(p),'-vn','-f','f32le','-ac','1','-ar','22050','-'],capture_output=True,check=True)
 samples=np.frombuffer(audio.stdout,dtype=np.float32);peak=float(np.abs(samples).max());rms=float(np.sqrt(np.mean(samples**2)))
 decode=subprocess.run([F,'-v','error','-i',str(p),'-f','null','-'],capture_output=True,text=True)
 data=p.read_bytes();moov=data.find(b'moov');mdat=data.find(b'mdat')
 checks={'vertical_9_16':abs(size[0]/size[1]-9/16)<.001,'duration_3_to_60':3<=duration<=60,'fps_23_to_60':23<=fps<=60,'h264':'Video: h264' in meta,'yuv420p':'yuv420p' in meta,'aac':'Audio: aac' in meta,'audible_no_clipping':.005<rms and peak<1,'faststart':0<moov<mdat,'full_decode_ok':decode.returncode==0,'under_1gb':len(data)<1_000_000_000}
 qc=InstagramContentEngine._validate_ig_video(None,video_path=p,target_seconds=duration,require_audio=True)
 default_qc=InstagramContentEngine._validate_ig_video(None,video_path=p,target_seconds=8,require_audio=True)
 record={'file':str(p.relative_to(R)),'duration_seconds':duration,'resolution':size,'fps':fps,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'checks':checks,'passed':all(checks.values()) and qc['passed'],'publisher_video_qc_matching_duration':qc,'publisher_video_qc_current_8s_default':default_qc,'audio_peak':peak,'audio_rms':rms,'codec_lines':[l.strip() for l in meta.splitlines() if 'Stream #' in l],'meta_upload_tested':False,'scheduled':False}
 reports.append(record);(p.parent/'validacion.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');print(p.name,record['passed'],duration,flush=True)
(O/'validacion_videos.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
assert all(x['passed'] for x in reports)
