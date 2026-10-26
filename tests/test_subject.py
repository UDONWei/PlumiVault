import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from subject_detector import choose_subject,square_box
class SubjectTests(unittest.TestCase):
 def test_missing_and_invalid_fall_back(self):
  for proposals in ([],[{'box':[0,0,1,1],'score':.2}],[{'box':[0,0,1,1],'score':float('nan')}],[{'box':[0,0,0,1],'score':.8}]):
   self.assertEqual(choose_subject(proposals)['status'],'no_detection')
 def test_internal_boundary_fragment_does_not_become_subject(self):
  result=choose_subject([{'box':[0,0,.2,.2],'score':.99,'internal_edge_cut':True},{'box':[.4,.4,.6,.6],'score':.8}])
  self.assertEqual(result['selected_score'],.8)
 def test_duplicate_and_multiple_birds(self):
  result=choose_subject([{'box':[.1,.1,.3,.3],'score':.9},{'box':[.11,.1,.31,.3],'score':.8},{'box':[.7,.7,.9,.9],'score':.7}])
  self.assertEqual(len(result['detections']),2);self.assertTrue(result['multiple_candidates'])
  self.assertLessEqual(result['selected_box'][0],.1);self.assertGreaterEqual(result['selected_box'][2],.3)
 def test_square_contains_subject_at_edges_and_preserves_full_size_box(self):
  for box in ([0,0,.1,.2],[.8,.8,1,1],[.1,.1,.3,.15]):
   square=square_box(box,(1000,500))
   self.assertAlmostEqual((square[2]-square[0])*1000,(square[3]-square[1])*500)
   self.assertTrue(all(0<=x<=1 for x in square))
   self.assertTrue(square[0]<=box[0] and square[1]<=box[1] and square[2]>=box[2] and square[3]>=box[3])
  self.assertEqual(square_box([0,0,1,1],(1000,500)),[0,0,1,1])
if __name__=='__main__':unittest.main()

