"""Recompose service posters locally from existing photos; no AI, database or publishing.
Produces a candidate registry only. Deploy and editorial approval are separate.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,sys
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw,ImageFont
from instagram_image_factory import DbService,compose_asset
from instagram_layout_guard import assert_layouts

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def build(app_root, snapshot, photos, output):
    app_root=Path(app_root).resolve();photos=Path(photos).resolve();output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError("Output must be empty")
    output.mkdir(parents=True,exist_ok=True);assets=output/"assets";assets.mkdir()
    data=json.loads(Path(snapshot).read_text(encoding="utf-8"))
    registry=copy.deepcopy(data["registry"]);records=[]
    for spec in data["services"]:
        code=spec["code"];old=app_root/"imagenes_ig"/spec["old_image"]
        if digest(old)!=spec["old_sha256"]:raise ValueError("Original approval changed: "+code)
        override=photos/(code+".png")
        raw=app_root/spec["raw_source"] if spec.get("raw_source") else None
        if override.is_file():source=override
        elif raw and raw.is_file() and raw.resolve().is_relative_to(app_root):source=raw
        else:
            # Native layout fallback: retain only the photographic panel.
            with Image.open(old) as im:
                box=(630,0,1080,620) if code=="desarrollo_web" else (630,100,1080,920)
                panel=ImageOps.fit(im.crop(box).convert("RGB"),(470,930))
                base=Image.new("RGB",(1080,1350),(250,250,250));base.paste(panel,(610,0))
                source=output/(code+"_source.png");base.save(source)
        target=assets/(code+"_editorial_v8.png")
        guard=compose_asset(base_path=source,output_path=target,service=DbService(code,spec["name"],spec["provider_count"]))
        assert_layouts([guard])
        (output/(code+"_layout.json")).write_text(json.dumps(guard.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
        row=registry["services"][code]
        row["previous_approval"]={"image":row["image"],"sha256":row["sha256"]}
        row.update(image=target.name,sha256=digest(target),status="approved",approval_source="editorial_review_v8",reason="")
        records.append({"code":code,"image":target.name,"sha256":digest(target),"source_sha256":digest(source),"old_image":spec["old_image"],"old_sha256":spec["old_sha256"]})
    (output/"candidate-registry.json").write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding="utf-8")
    (output/"review.json").write_text(json.dumps({"status":"pending_visual_review","entries":records},ensure_ascii=False,indent=2),encoding="utf-8")
    font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",17)
    for page in range((len(records)+8)//9):
        sheet=Image.new("RGB",(1080,1500),"#e7e9e7");d=ImageDraw.Draw(sheet)
        for i,row in enumerate(records[page*9:(page+1)*9]):
            with Image.open(assets/row["image"]) as im:im.thumbnail((346,433));sheet.paste(im,((i%3)*360,(i//3)*500))
            d.text(((i%3)*360+4,(i//3)*500+441),row["code"],font=font,fill="black")
        sheet.save(output/(f"repaired_{page+1}.jpg"),quality=92)
    print(json.dumps({"candidate_images":len(records),"output":str(output)}))

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ["app-root","snapshot","photos","output"]:p.add_argument("--"+arg,type=Path,required=True)
    a=p.parse_args();build(a.app_root,a.snapshot,a.photos,a.output)
