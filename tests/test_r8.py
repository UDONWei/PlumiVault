"""Synthetic files only: display state, burst boundaries and quarantine compatibility."""
import contextlib,json,sqlite3,unittest
from unittest.mock import patch
from pathlib import Path
from test_prototype import Fixture
from bird_index.visibility import set_visibility
from bird_index.selection import set_selection
from bird_index.db import Database,Conflict
from bird_index.library import Library
from bird_index.curation import Organizer

class StudioR8Tests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture()
  for name in ('date/a.ARW','date/b.ARW','date/c.ARW'):self.f.file(name)
  self.f.scan();self.f.db.review([{'id':i,'revision':0} for i in (1,2,3)],'confirmed',['Bird alpha'])
 def tearDown(self):self.f.close()
 def photos(self,**filters):return self.f.lib.listing({'mode':'photos','bursts':'1','state':'any',**filters})
 def test_visibility_is_independent_persistent_and_no_photo_reads(self):
  set_selection(self.f.db,[{'id':1,'revision':0}],'keep',5)
  before=self.f.lib.items()[0]
  with patch('pathlib.Path.open',side_effect=AssertionError('no original reads')):
   set_visibility(self.f.db,[{'id':1,'revision':0}],True)
   self.assertEqual(self.photos()['total'],2)
   self.assertEqual(self.photos(visibility='hidden')['items'][0]['id'],1)
  lib=Library(Database(self.f.data),self.f.cfg);p=lib.items()[0]
  self.assertTrue(p['visibility']['hidden']);self.assertEqual(p['manual'],before['manual']);self.assertEqual(p['selection'],before['selection'])
  set_visibility(self.f.db,[{'id':1,'revision':1}],False);self.assertEqual(self.photos()['total'],3)
  self.f.db.review([{'id':1,'revision':1}],'no_bird',[])
  self.assertEqual(self.photos()['total'],3,'No-bird is a classification; independent visibility controls hiding')
 def test_batch_rollback_conflict_validation(self):
  set_visibility(self.f.db,[{'id':2,'revision':0}],True)
  with self.assertRaises(Conflict):set_visibility(self.f.db,[{'id':1,'revision':0},{'id':2,'revision':0}],True)
  self.assertFalse(self.f.lib.items()[0]['visibility']['hidden'])
  for items,hidden in [([],True),([{'id':1,'revision':0}],1),([{'id':True,'revision':0}],True),([{'id':1,'revision':0}]*2,True)]:
   with self.assertRaises(ValueError):set_visibility(self.f.db,items,hidden)
 def test_hidden_backup_export_reprocessing(self):
  set_visibility(self.f.db,[{'id':1,'revision':0}],True);self.f.scan(force=True)
  self.assertTrue(self.f.lib.items()[0]['visibility']['hidden'])
  backup=self.f.db.backup()
  with contextlib.closing(sqlite3.connect(backup)) as c:self.assertEqual(c.execute('SELECT hidden FROM visibility WHERE photo_id=1').fetchone()[0],1)
  text=self.f.lib.export_csv({'visibility':'hidden'}).decode('utf-8-sig');self.assertIn('已隐藏',text);self.assertIn('date/a.ARW',text);self.assertNotIn('date/b.ARW',text)
 def test_group_respects_hidden_boundary_pagination_and_no_image_similarity(self):
  with patch('bird_index.grouping.similar',side_effect=AssertionError('unneeded image comparison')):
   result=self.photos(limit='2');self.assertEqual(result['bursts'][0]['ids'],[1,2]);self.assertEqual(result['bursts'][0]['matched_count'],3)
  result=self.photos(offset='2',limit='2');self.assertEqual(result['bursts'][0]['ids'],[3]);self.assertEqual(result['bursts'][0]['count'],3)
  set_visibility(self.f.db,[{'id':2,'revision':0}],True);self.f.db.review([{'id':2,'revision':1}],'confirmed',['Bird beta'])
  result=self.photos();self.assertEqual([g['ids'] for g in result['bursts']],[[1],[3]],'Filtering must not join bursts across an intervening different bird')
 def organizer(self):
  dest=self.f.base/'quarantine';dest.mkdir(exist_ok=True)
  return Organizer(self.f.db,{'enabled':True,'root_id':'fixture','photo_root':str(self.f.root),'quarantine_root':str(dest),'allowed_photo_ids':[1],'max_batch':10}),dest
 def test_flat_new_layout_collision_and_repeated_restore(self):
  org,dest=self.organizer();set_selection(self.f.db,[{'id':1,'revision':0}],'reject',4)
  for _ in range(2):
   plan=org.plan([1],'move');self.assertEqual(plan['items'][0]['destination'],'date/a.ARW')
   self.assertTrue(org.commit(plan['plan_id'])['results'][0]['ok']);self.assertTrue((dest/'date/a.ARW').is_file())
   self.assertTrue(org.commit(org.plan([1],'restore')['plan_id'])['results'][0]['ok'])
  (dest/'date/a.ARW').write_bytes(b'existing')
  with self.assertRaises(Conflict):org.plan([1],'move')
  self.assertEqual((dest/'date/a.ARW').read_bytes(),b'existing');self.assertTrue((self.f.root/'date/a.ARW').is_file())
 def test_overlapping_previews_do_not_create_duplicate_move_records(self):
  org,dest=self.organizer();set_selection(self.f.db,[{'id':1,'revision':0}],'reject',0)
  one,two=org.plan([1],'move'),org.plan([1],'move');org.commit(one['plan_id'])
  with self.assertRaises(Conflict):org.commit(two['plan_id'])
  self.assertEqual(len(self.f.db.query('SELECT * FROM file_moves')),1)
  one,two=org.plan([1],'restore'),org.plan([1],'restore');org.commit(one['plan_id'])
  with self.assertRaises(Conflict):org.commit(two['plan_id'])
  self.assertEqual(self.f.db.query("SELECT * FROM file_moves WHERE state='moved'"),[])
 def test_legacy_nested_journal_restore(self):
  org,dest=self.organizer();set_selection(self.f.db,[{'id':1,'revision':0}],'reject',0);plan=org.plan([1],'move')
  plan['items'][0]['destination']='old-plan/fixture/date/a.ARW'
  with self.f.db.transaction() as c:c.execute('UPDATE file_plans SET payload=? WHERE id=?',(json.dumps(plan['items']),plan['plan_id']))
  self.assertTrue(org.commit(plan['plan_id'])['results'][0]['ok'])
  restore=org.plan([1],'restore');self.assertEqual(restore['items'][0]['destination'],'old-plan/fixture/date/a.ARW');self.assertTrue(org.commit(restore['plan_id'])['results'][0]['ok'])
 def test_schema4_backup_before_upgrade(self):
  with self.f.db.transaction() as c:
   c.execute('DROP TABLE visibility');c.execute("UPDATE meta SET value='4' WHERE key='schema'")
  db=Database(self.f.data);self.assertEqual(db.meta('schema'),'5')
  backups=list((self.f.data/'backups').glob('*.sqlite3'));self.assertTrue(backups)
  with contextlib.closing(sqlite3.connect(backups[-1])) as c:
   self.assertEqual(c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0],'4')
   self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='visibility'").fetchone())

if __name__=='__main__':unittest.main()
