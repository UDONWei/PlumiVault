"""Thumbnail click regression; synthetic metadata, no original photo reads."""
import os,shutil,subprocess,unittest
import os, shutil
from pathlib import Path

class StudioTests(unittest.TestCase):
 def test_thumbnail_navigation_and_selection(self):
  root=Path(__file__).resolve().parents[1]
  node=os.environ.get('BIRD_NODE') or shutil.which('node')
  if not node:
   bundled=Path(os.environ.get('BIRD_NODE') or shutil.which('node') or 'node')
   if bundled.is_file():node=str(bundled)
  if not node:self.skipTest('Node.js unavailable; thumbnail interaction test not run')
  result=subprocess.run([node,str(root/'tests/check_studio_thumbnails.js'),str(root/'web/studio.js')],capture_output=True,text=True,encoding='utf-8',timeout=20)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
