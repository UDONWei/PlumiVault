"""Synthetic compact deployment tests; never connect to NAS or read photos."""
import ctypes
import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from bird_index import compact, compact_sandbox as sandbox
from bird_index.common import PROJECT
from bird_index import organizer_client


def bpf_result(rows, number, *, arch=0xc000003e, arg1=0):
    """Small interpreter for the classic BPF instructions used by our filter."""
    data={0:number,4:arch,24:arg1};acc=0;pc=0
    while pc<len(rows):
        code,jt,jf,k=rows[pc]
        if code==0x20:acc=data[k]
        elif code==0x15:pc+=jt if acc==k else jf
        elif code==0x35:pc+=jt if acc>=k else jf
        elif code==0x06:return k
        else:raise AssertionError('Unknown BPF instruction')
        pc+=1
    raise AssertionError('No BPF return')


class SandboxTests(unittest.TestCase):
    def test_metadata_and_abi_escape_denied(self):
        rows=sandbox.metadata_filter();denied=0x50000|errno.EPERM
        for number in sandbox.METADATA_CALLS:
            self.assertEqual(bpf_result(rows,number),denied,number)
        for number in (101,310,311,425,426,427,438):
            self.assertEqual(bpf_result(rows,number),denied,number)
        for number in (0,1,2,3,9,41,56,59,257,444,445,446):
            self.assertEqual(bpf_result(rows,number),0x7fff0000,number)
        self.assertEqual(bpf_result(rows,0x40000000|91),0x80000000)
        self.assertEqual(bpf_result(rows,91,arch=0x40000003),0x80000000)
        self.assertEqual(bpf_result(rows,16,arg1=0x40086602),denied) # FS_IOC_SETFLAGS
        self.assertEqual(bpf_result(rows,16,arg1=0x5401),0x7fff0000)

    def test_gateway_fchmod_exception_requires_read_sandbox(self):
        rows=sandbox.metadata_filter(True)
        self.assertEqual(bpf_result(rows,91),0x7fff0000)
        self.assertEqual(bpf_result(rows,452),0x50000|errno.EPERM)
        with self.assertRaises(ValueError):sandbox.restrict([],allow_fchmod=True)

    def test_old_abi_fails_before_rules_or_servers(self):
        with patch.object(sandbox,'libc'),patch.object(sandbox,'abi_version',return_value=5),patch.object(sandbox,'checked') as calls:
            with self.assertRaises(RuntimeError):sandbox.restrict([])
            calls.assert_not_called()
        with patch.object(compact,'configuration'),patch.object(compact,'probe',side_effect=RuntimeError('blocked')),patch.object(compact.subprocess,'Popen') as spawn:
            with self.assertRaises(RuntimeError):compact.supervise()
            spawn.assert_not_called()

    def test_ctypes_layout_and_seccomp_fail_closed(self):
        self.assertEqual(ctypes.sizeof(sandbox.Ruleset),24)
        self.assertEqual(ctypes.sizeof(sandbox.PathRule),12)
        self.assertEqual(ctypes.sizeof(sandbox.PortRule),16)
        lib=Mock();lib.prctl.return_value=-1
        with self.assertRaises(OSError):sandbox.restrict_metadata(lib)

    @unittest.skipUnless(sys.platform=='linux','Real Landlock/seccomp test requires Linux; migration always runs it on NAS')
    def test_real_synthetic_probe(self):
        sandbox.probe()


class SupervisorTests(unittest.TestCase):
    def test_worker_policy_does_not_allow_library_writes(self):
        writes,bind,connect=compact.role_policy('index',{})
        self.assertEqual(writes,['/data','/tmp','/dev/null'])
        self.assertEqual((bind,connect),([8765],[8766]))
        with self.assertRaises(ValueError):compact.role_policy('unknown',{})

    def test_failed_child_tears_down_all_process_groups(self):
        children=[Mock(pid=i,poll=Mock(return_value=None)) for i in (101,102,103)]
        children[1].poll.return_value=1
        with patch.object(compact,'configuration'),patch.object(compact,'probe'),patch.object(compact.signal,'signal'),patch.object(compact.Path,'exists',return_value=False),patch.object(compact.subprocess,'Popen',side_effect=children),patch.object(compact,'stop_children') as stop:
            self.assertEqual(compact.supervise(),1);stop.assert_called_once_with(children)

    def test_role_is_never_executed_without_sandbox(self):
        with patch.object(compact,'configuration',return_value={}),patch.object(compact,'restrict',side_effect=PermissionError('denied')),patch.object(compact.os,'execvpe') as execute:
            with self.assertRaises(PermissionError):compact.child('index')
            execute.assert_not_called()

    def test_loopback_organizer_is_explicit_opt_in(self):
        with patch.dict(os.environ,{'BIRD_ORGANIZER_URL':'http://127.0.0.1:8766','BIRD_COMPACT':'0'}):
            self.assertFalse(organizer_client.call('status',{})['enabled'])
        with patch.dict(os.environ,{'BIRD_ORGANIZER_URL':'http://127.0.0.1:8766','BIRD_COMPACT':'1','BIRD_GATEWAY_TOKEN_FILE':'synthetic'}),patch.object(Path,'read_text',return_value='x'*40),patch.object(organizer_client.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=RuntimeError('request reached transport')
            with self.assertRaisesRegex(RuntimeError,'transport'):organizer_client.call('status',{})
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,'http://127.0.0.1:8766/status')


# Docker command simulator: tests shell ordering/rollback, not Docker itself.
FAKE_DOCKER=r'''
import json,os,sys
from pathlib import Path
a=sys.argv[1:];root=Path.cwd();statefile=root/'fake-state.json';s=json.loads(statefile.read_text())
s['calls'].append(a);result='';code=0
stage=os.environ.get('FAKE_FAIL','')
if a[0]=='inspect':
 fmt=a[2];cid=a[-1]
 if '.Image' in fmt:result='sha256:synthetic-'+cid
 elif '.RW' in fmt:result='false'
 elif '.Source' in fmt:
  target=fmt.split('eq .Destination "')[1].split('"')[0]
  if target=='/photos':result='/synthetic/photos'
  elif target=='/library':result='/synthetic'
  else:result=root.as_posix()+('/gateway-'+target.lstrip('/') if cid=='old-gateway' else target)
elif a[0]=='exec':
 data=sys.stdin.read()
 if '--probe' in a and stage=='probe':code=1
 elif '--backup' in a and stage=='backup':code=1
elif a[0]=='compose':
 mode='rollback' if '--project-directory' in a else ('compact' if 'compose.compact.yaml' in a else 'legacy')
 command=next(x for x in a if x in ('ps','config','build','stop','rm','up','exec'))
 if command=='ps' and ('-q' in a or '-aq' in a):
  role=a[-1];result=('old-'+role) if role!='app' else ('new-app' if s['app'] else '')
 elif command=='config' and '--format' in a:result='{}'
 elif command=='build' and stage=='build':code=1
 elif command=='rm':
  if mode=='compact':s['app']=False
  else:s['old']=False
 elif command=='up':
  if mode=='compact':
   assert not s['old'], 'New app would exceed slot limit before removing old services'
   s['app']=True
   if stage=='health':code=1
  elif mode=='rollback':
   assert not s['app'], 'Rollback must remove app before recreating old services'
   s['old']=True;s['restored']=True
statefile.write_text(json.dumps(s));print(result,end='\n' if result else '');sys.exit(code)
'''


class MigrationShellTests(unittest.TestCase):
    def run_migration(self,fail=''):
        shell=os.environ.get('BIRD_SH') or shutil.which('sh')
        if not shell:self.skipTest('POSIX shell unavailable')
        with tempfile.TemporaryDirectory(prefix='compact-test-',dir=os.environ.get('BIRD_TEST_TEMP')) as temp:
            root=Path(temp);(root/'deploy/gateway').mkdir(parents=True);(root/'config').mkdir();(root/'bird_index').mkdir();(root/'tools').mkdir()
            for name in ('merge-containers.sh','compact-command.sh'):
                shutil.copyfile(PROJECT/'deploy'/name,root/'deploy'/name)
            for name in ('.env','compose.yaml','compose.offline.yaml','compose.curation.yaml','config/curation.enabled','config/curation.json','bird_index/compact_sandbox.py','tools/compact_preflight.py'):
                (root/name).write_text('synthetic\n',encoding='utf-8')
            (root/'deploy/gateway/Caddyfile').write_text('reverse_proxy index:8765\n')
            (root/'fake-docker.py').write_text(FAKE_DOCKER,encoding='utf-8')
            (root/'fake-state.json').write_text(json.dumps({'old':True,'app':False,'restored':False,'calls':[]}))
            env=dict(os.environ,FAKE_FAIL=fail,BIRD_TEST_PYTHON=Path(sys.executable).as_posix(),BIRD_TEST_ROOT=root.as_posix())
            env['PATH']=str(Path(shell).parent)+os.pathsep+env.get('PATH','')
            command='pwd() { printf "%s\\n" "$BIRD_TEST_ROOT"; }; docker() { "$BIRD_TEST_PYTHON" fake-docker.py "$@"; }; . ./deploy/merge-containers.sh'
            run=subprocess.run([shell,'-c',command],cwd=root,env=env,capture_output=True,text=True,timeout=60)
            state=json.loads((root/'fake-state.json').read_text());state['marker']=(root/'config/compact.enabled').exists()
            state['locked']=(root/'config/.compact-operation-lock').exists()
            return run,state

    def test_success_uses_two_app_slots_only_after_removing_old_services(self):
        run,s=self.run_migration();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertTrue(s['app']);self.assertFalse(s['old']);self.assertTrue(s['marker']);self.assertFalse(s['locked'])
        for call in s['calls']:
            self.assertNotIn('down',call);self.assertNotIn('-v',call);self.assertNotIn('prune',call)
            self.assertNotIn('plumivault-tailscale',' '.join(call))

    def test_preflight_and_build_failure_do_not_stop_old_services(self):
        for fail in ('probe','build'):
            run,s=self.run_migration(fail);self.assertNotEqual(run.returncode,0)
            self.assertTrue(s['old']);self.assertFalse(s['marker']);self.assertFalse(s['locked'])
            self.assertFalse(any('stop' in a for a in s['calls']))

    def test_failed_backup_or_new_health_restores_previous_services(self):
        for fail in ('backup','health'):
            run,s=self.run_migration(fail);self.assertNotEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertTrue(s['old']);self.assertTrue(s['restored']);self.assertFalse(s['app']);self.assertFalse(s['marker']);self.assertFalse(s['locked'])


if __name__=='__main__':unittest.main()
