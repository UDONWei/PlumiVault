"""仅在内存计算外观摘要；用于可恢复折叠，不证明像素相同或照片优劣。"""
import numpy as np
from PIL import Image

def describe(image):
    with image.resize((32,32),Image.Resampling.LANCZOS).convert("L") as gray:
        values=np.asarray(gray,dtype=np.float64)
    basis=np.cos(np.pi*(np.arange(32)+.5)[None,:]*np.arange(8)[:,None]/32)
    coeff=basis@values@basis.T
    vector=coeff.flatten()[1:]
    bits=vector>np.median(vector)
    phash=format(sum(int(b)<<i for i,b in enumerate(bits)),"016x")
    with image.resize((9,8),Image.Resampling.LANCZOS).convert("L") as gray:
        v=np.asarray(gray,dtype=np.float64)
        bits=(v[:,1:]>v[:,:-1]).flatten()
    dhash=format(sum(int(b)<<i for i,b in enumerate(bits)),"016x")
    with image.resize((64,64),Image.Resampling.BILINEAR).convert("RGB") as small:
        rgb=np.asarray(small,dtype=np.float64)/255
    g=rgb.mean(axis=2)
    lap=-4*g[1:-1,1:-1]+g[:-2,1:-1]+g[2:,1:-1]+g[1:-1,:-2]+g[1:-1,2:]
    return {"phash":phash,"dhash":dhash,"mean_rgb":rgb.mean(axis=(0,1)).round(5).tolist(),
            "detail_score":round(float(lap.var()),7),"aspect":round(image.width/image.height,6),
            "algorithm":"dct63-dhash64-rgb-v1"}
