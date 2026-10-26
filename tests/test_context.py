"""背景排序正确性测试，合成分数不作为真实鸟类识别结果。"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'tools'))
from context_prior import POLICY, load_occurrences, prior_factor, rank_scores, resolve_context, validate_context
from rerank_context_report import rerank

LABELS = [{'kind':'bird','scientific_name':name,'prompt':name} for name in ['unknown','summer','winter','passage','resident','vagrant']]
LABELS.append({'kind':'control_non_species','prompt':'a rock'})
DATA = {'regions': {'IIA':'黄淮平原亚区'}, 'species': {
    'summer':{'IIA':['S']}, 'winter':{'IIA':['W']}, 'passage':{'IIA':['P']},
    'resident':{'IIA':['R']}, 'vagrant':{'IIA':['V']}}}


class CaptureContext(unittest.TestCase):
    def test_date_priority_conflicts_and_truth_separation(self):
        result = resolve_context({'date':'2026-10-06','region_code':'IIA'}, {'date':'2026-10-07'},
            {'EXIF DateTimeOriginal':'2026:10:08 12:34:56'}, '20261009拍摄', 'a.arw', DATA['regions'])
        self.assertEqual(result['date'],'2026-10-07')
        self.assertEqual(result['date_source'],'sample_override')
        self.assertEqual(result['folder_date'],'2026-10-09')
        self.assertEqual(result['region_code'],'IIA')
        self.assertTrue(result['warnings'])
        self.assertNotIn('truth',result)

    def test_exif_folder_invalid_and_missing_date(self):
        exif={'EXIF DateTimeOriginal':'2026:10:07 23:59:59'}
        result=resolve_context({}, {}, exif, '20261008景点','a.jpg')
        self.assertEqual(result['date_source'],'EXIF DateTimeOriginal')
        self.assertEqual(result['date'],'2026-10-07')
        result=resolve_context({}, {}, {'EXIF DateTimeOriginal':'bad'}, '20261007景点','2026-02-29/a.jpg')
        self.assertEqual(result['date_source'],'folder_name')
        self.assertEqual(result['date'],'2026-10-07')
        self.assertEqual(len(result['warnings']),2)
        self.assertIsNone(resolve_context({}, {}, {}, 'photos','a.jpg')['date'])

    def test_validation_and_null_override(self):
        for invalid in ({'date':'2026-02-29'},{'date':'2026-1-1'},{'region_code':'wrong'},
                        {'use_date':'yes'},{'latitude':39},{'location':123}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError): validate_context(invalid,DATA['regions'])
        context=resolve_context({'region_code':'IIA'}, {'region_code':None}, {},'photos','a.jpg',DATA['regions'])
        self.assertIsNone(context['region_code'])

    def test_missing_region_neutral_and_dates_optional(self):
        for label in LABELS:
            self.assertEqual(prior_factor(label,{'date':'2026-10-07'},DATA)['factor'],1)
        self.assertEqual(prior_factor(LABELS[1],{'region_code':'IIA'},DATA)['factor'],1.15)
        self.assertEqual(prior_factor(LABELS[1],{'region_code':'IIA','date':'2026-07-01','use_date':False},DATA)['factor'],1.15)

    def test_month_boundaries_and_neutral_unknown_vagrant_controls(self):
        for month in range(1,13):
            context={'region_code':'IIA','date':f'2026-{month:02d}-01'}
            for index,season in [(1,'S'),(2,'W'),(3,'P'),(4,'R')]:
                factor=prior_factor(LABELS[index],context,DATA)['factor']
                self.assertEqual(factor,1.25 if month in POLICY['months'][season] else 1.15)
            for index in (0,5,6): self.assertEqual(prior_factor(LABELS[index],context,DATA)['factor'],1)

    def test_full_pool_rerank_keeps_visual_and_limits_influence(self):
        labels=copy.deepcopy(LABELS)
        scores=[.20,.17,.16,.18,.12,.10,.07]
        snapshot=copy.deepcopy((labels,scores))
        ranked=rank_scores(labels,scores,{'region_code':'IIA','date':'2026-10-07'},DATA,k=1)
        self.assertEqual(ranked['candidates'][0]['label']['scientific_name'],'unknown')
        self.assertEqual(ranked['context_candidates'][0]['label']['scientific_name'],'passage')
        self.assertEqual(ranked['context_candidates'][0]['visual_rank'],2)
        self.assertEqual((labels,scores),snapshot)
        scores=[.8,.03,.03,.05,.03,.03,.03]
        ranked=rank_scores(labels,scores,{'region_code':'IIA','date':'2026-10-07'},DATA,k=7)
        self.assertEqual(ranked['context_candidates'][0]['label']['scientific_name'],'unknown')
        self.assertEqual(len(ranked['context_candidates']),7)

    def test_rejects_topk_partial_vector_and_invalid_scores(self):
        for scores in ([.4]*7,[float('nan')]+[.1]*6,[-.1]+[1.1/6]*6,[.2]):
            with self.subTest(scores=scores), self.assertRaises(ValueError): rank_scores(LABELS,scores,{},DATA)

    def test_dataset_mapping_and_taxonomy_complete(self):
        data=load_occurrences(PROJECT/'docs/china-birds-occurrence-ioc12.1.json')
        labels=json.loads((PROJECT/'docs/china-birds-ioc12.1-probe.json').read_text(encoding='utf-8'))['labels']
        self.assertEqual(len(data['regions']),19)
        self.assertEqual(len(data['species']),1481)
        self.assertEqual(set(data['species']),{l['scientific_name'] for l in labels if l['kind']=='bird'})
        self.assertEqual(data['period'],'Zheng, 2017')

    def test_rerank_no_photos_and_preserves_truth(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            scores=[1/7]*7
            view={**rank_scores(LABELS,scores,{},None), 'name':'whole','all_visual_scores':scores}
            source={'photos_root':'NONEXISTENT/20261007folder','score_labels':LABELS,
                'rows':[{'path':'nonexistent.ARW','truth':{'scientific_name':'human-confirmed'},'views':[view]}]}
            (base/'source.json').write_text(json.dumps(source),encoding='utf-8')
            manifest={'capture_context':{'region_code':'IIA'},'samples':[{'path':'nonexistent.ARW','truth':'must not overwrite'}]}
            (base/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            result=rerank(base/'source.json',base/'manifest.json',PROJECT/'docs/china-birds-occurrence-ioc12.1.json',base/'result.json')
            self.assertEqual(result['rows'][0]['truth'],source['rows'][0]['truth'])
            self.assertEqual(result['rows'][0]['capture_context']['date'],'2026-10-07')
            self.assertEqual(result['rows'][0]['views'][0]['candidates'],view['candidates'])
            with self.assertRaises(FileExistsError): rerank(base/'source.json',base/'manifest.json',PROJECT/'docs/china-birds-occurrence-ioc12.1.json',base/'result.json')

    def test_javascript_python_parity_all_regions_months(self):
        node=shutil.which('node')
        if not node: self.skipTest('Node 不可用，未验证浏览器排序的一致性')
        data=load_occurrences(PROJECT/'docs/china-birds-occurrence-ioc12.1.json')
        labels=json.loads((PROJECT/'docs/china-birds-ioc12.1-probe.json').read_text(encoding='utf-8'))['labels']
        # 完整全国标签的合成分数，覆盖所有 19 亚区和 12 个月。
        scores=[(i%11+1) for i in range(len(labels))]; total=sum(scores); scores=[s/total for s in scores]
        contexts=[{'region_code':code,'date':f'2026-{month:02d}-07'} for code in data['regions'] for month in range(1,13)]
        code='''const fs=require('fs'), api=require(process.argv[1]); const x=JSON.parse(fs.readFileSync(0,'utf8')); process.stdout.write(JSON.stringify({dates:['2026-02-29','2024-02-29','0000-01-01','2026-10-07'].map(api.validDate), results:x.contexts.map(c=>api.rank(x.labels,x.scores,c,x.data,x.policy).adjusted)}));'''
        result=subprocess.run([node,'-e',code,str(PROJECT/'tools/context_rank.js')],
            input=json.dumps({'data':data,'labels':labels,'scores':scores,'contexts':contexts,'policy':POLICY}),
            capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)
        js=json.loads(result.stdout)
        self.assertEqual(js['dates'],[False,True,False,True])
        for context,actual in zip(contexts,js['results']):
            expected=rank_scores(labels,scores,context,data)['context_candidates']
            for a,e in zip(actual,expected):
                self.assertEqual(labels[a['i']],e['label'])
                for key in ('factor','visual_rank','statuses','reasons','ranking_score'): self.assertEqual(a[key],e[key])

    def test_report_write_into_photo_root_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            photos=base/'substitute-photo-root'
            photos.mkdir()
            source=base/'source.json'
            source.write_text(json.dumps({'photos_root':str(photos)}),encoding='utf-8')
            with self.assertRaises(ValueError):
                rerank(source,base/'unused.json',base/'unused-priors.json',photos/'report.json')
            self.assertEqual(list(photos.iterdir()),[])


if __name__=='__main__': unittest.main()
