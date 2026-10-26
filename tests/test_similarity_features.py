import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from PIL import Image
import numpy as np
from similarity_features import describe
class SimilarityFeatures(unittest.TestCase):
    def test_deterministic_and_bounded(self):
        rng=np.random.default_rng(2026)
        image=Image.fromarray(rng.integers(0,256,(120,160,3),dtype=np.uint8))
        a=describe(image);b=describe(image.copy())
        self.assertEqual(a,b)
        self.assertEqual(len(a["phash"]),16)
        self.assertTrue(all(0<=x<=1 for x in a["mean_rgb"]))
        self.assertGreater(a["detail_score"],0)
    def test_different_colour_not_collapsed_by_flat_hash(self):
        a=describe(Image.new("RGB",(100,100),"red"))
        b=describe(Image.new("RGB",(100,100),"blue"))
        self.assertGreater(sum((x-y)**2 for x,y in zip(a["mean_rgb"],b["mean_rgb"])),1)
if __name__=="__main__":unittest.main()
