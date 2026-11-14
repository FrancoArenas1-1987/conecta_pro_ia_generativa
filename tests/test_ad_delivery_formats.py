from pathlib import Path
import sys
import numpy as np
from PIL import Image
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from prepare_contact_ads import delivery

@pytest.mark.parametrize(("story","feed_format","native_story","source_size","target_size"),[
    (False,"portrait",False,(800,1000),(1080,1350)),
    (False,"square",False,(800,800),(1080,1080)),
    (True,"portrait",True,(576,1024),(1080,1920)),
    (True,"portrait",False,(800,1000),(1080,1920)),
])
def test_delivery_preserves_full_artwork_and_distinct_formats(tmp_path,story,feed_format,native_story,source_size,target_size):
    im=Image.new("RGB",source_size,"white")
    w,h=source_size
    # Colored panels touching every edge expose any crop or stretch of a tall/square source.
    from PIL import ImageDraw
    d=ImageDraw.Draw(im)
    d.rectangle((0,0,w//3,h//3),fill="red")
    d.rectangle((w*2//3,0,w-1,h//3),fill="green")
    d.rectangle((0,h*2//3,w//3,h-1),fill="blue")
    d.rectangle((w*2//3,h*2//3,w-1,h-1),fill="yellow")
    src=tmp_path/"source.png";out=tmp_path/"delivery.jpg";im.save(src)
    delivery(src,out,story=story,background="FFFFFF",feed_format=feed_format,native_story=native_story)
    with Image.open(out) as result:
        assert result.size==target_size and result.format=="JPEG"
        tw,th=target_size
        content_h=1350 if story and not native_story else th
        offset=(th-content_h)//2
        for x,y,channel in [(tw//6,offset+content_h//6,0),(tw//6,offset+content_h*5//6,2)]:
            pixel=result.getpixel((x,y))
            assert pixel[channel]>180 and all(pixel[channel]>pixel[c]+80 for c in range(3) if c!=channel)
        green=result.getpixel((tw*5//6,offset+content_h//6))
        assert green[1]>green[0]+60 and green[1]>green[2]+60
        yellow=result.getpixel((tw*5//6,offset+content_h*5//6))
        assert yellow[0]>180 and yellow[1]>180 and yellow[2]<70
