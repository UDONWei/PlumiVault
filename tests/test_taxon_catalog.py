import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from taxon_catalog import annotate
class TaxonCatalog(unittest.TestCase):
 def fixture(self):
  return {'source_page':'https://example.test','title':'fixture','retrieved_date':'2026-10-24','response_sha256':'fixture','taxa':[{'latinname':'Bird alpha','name':'新名','enable':1,'id':1},{'latinname':'Bird beta','name':'乙一','enable':1,'id':2},{'latinname':'Bird beta','name':'乙二','enable':1,'id':3}]}
 def test_preserve_identity_and_ambiguous(self):
  labels=[{'kind':'bird','scientific_name':'Bird alpha','zh_name':'旧名'},{'kind':'bird','scientific_name':'Bird beta'},{'kind':'bird','scientific_name':'Bird gamma'},{'kind':'control','prompt':'not bird'}]
  before=copy.deepcopy(labels);report=annotate(labels,self.fixture())
  self.assertEqual([l.get('scientific_name') for l in labels],[l.get('scientific_name') for l in before]);self.assertEqual(labels[0]['zh_name'],'旧名');self.assertIn('旧名',labels[0]['aliases']);self.assertEqual(labels[0]['birdreport']['zh_name'],'新名')
  self.assertNotIn('birdreport',labels[1]);self.assertNotIn('birdreport',labels[2]);self.assertEqual(report['counts'],{'exact_scientific_name':1,'ambiguous':1,'unmatched':1})
 def test_search_alias_is_not_a_second_species(self):
  fixture=self.fixture();fixture['taxa'].append({**fixture['taxa'][0],'pinyin':'oldpinyin','guidebooksn':1521})
  labels=[{'kind':'bird','scientific_name':'Bird alpha','zh_name':'旧名'}];result=annotate(labels,fixture)
  self.assertEqual(result['counts'],{'exact_scientific_name':1});self.assertIn('oldpinyin',labels[0]['aliases']);self.assertEqual(labels[0]['birdreport']['id'],1)
 def test_do_not_map_chinese_name_alone(self):
  labels=[{'kind':'bird','scientific_name':'Other species','zh_name':'新名'}];annotate(labels,self.fixture());self.assertNotIn('birdreport',labels[0])
if __name__=='__main__':unittest.main()
