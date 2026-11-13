"""Display atlas regions as UI cards; preserve the original generated artwork files."""
from functools import lru_cache
from pathlib import Path
from PIL import Image
from shape_engine import GROUPS

ASSETS=Path(__file__).parent/'shape_assets'
# Observed row gutters in all three matched atlases, rather than assuming equal rows.
ROWS=((0,.277),(.277,.509),(.509,.765),(.765,1.))

@lru_cache(maxsize=3)
def atlas(family):
    if family not in ('lean','normal','heavy'):raise ValueError('未知示意图类别')
    with Image.open(ASSETS/f'{family}-atlas-v1.png') as source:
        return source.convert('RGB')

def cards(family,size=(144,180)):
    image=atlas(family);w,h=image.size;out={}
    for row,key in enumerate(GROUPS):
        lo,hi=ROWS[row]
        for i in range(3):
            part=image.crop((round(i*w/3),round(lo*h),round((i+1)*w/3),round(hi*h)))
            part.thumbnail((size[0]-6,size[1]-6),Image.Resampling.LANCZOS)
            canvas=Image.new('RGB',size,'#faf7f0')
            canvas.paste(part,((size[0]-part.width)//2,(size[1]-part.height)//2))
            out[key,i]=canvas
    return out
