"""Collect actual host C execution coverage from the existing Python native suites.

The compiler wrapper copies .gcno before disposable test directories vanish;
profile data is written outside those directories. No device/toolchain execution
or physical qualification follows from this report.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
def matching_notes(data,profile):
 data=Path(data);profile=Path(profile);candidates=[data.with_suffix('.gcno')]
 if '#' in data.name:
  invocation=profile/data.relative_to(profile).parts[0]
  decoded=Path(data.name.replace('#','/').lstrip('/'))
  if '..' not in decoded.parts:candidates.append((invocation/decoded).with_suffix('.gcno'))
 stamp=data.read_bytes()[4:12]
 for notes in candidates:
  if notes.is_file() and len(stamp)==8 and notes.read_bytes()[4:12]==stamp:return notes
 raise ValueError('Executed profile has no matching compiler map')

WRAPPER='''#!/usr/bin/env python3
import glob,os,re,shutil,subprocess,sys,time,uuid
from pathlib import Path
args=sys.argv[1:]
if any(x in args for x in ('--version','-dumpversion','-dumpmachine','-print-search-dirs')):raise SystemExit(subprocess.call([os.environ['VOMAR_REAL_GCC'],*args]))
sources=[a for a in args if a.endswith(('.c','.S')) and not a.startswith('-')]
root=Path(os.environ['VOMAR_C_SOURCE_ROOT']).resolve()
profile=Path(os.environ['VOMAR_C_PROFILE'])/uuid.uuid4().hex;profile.mkdir();started=time.time()
common=['--coverage','-fprofile-abs-path','-fprofile-filter-files='+re.escape(str(root))+'/', '-fprofile-dir='+str(profile)]
extra=[]
if len(sources)>1 and '-c' not in args and '-fsyntax-only' not in args:
 directory=profile/'objects';directory.mkdir();objects={}
 flags=[a for a in args if a not in sources]
 if '-o' in flags:
  index=flags.index('-o');del flags[index:index+2]
 for i,source in enumerate(sources):
  obj=directory/('unit'+str(i)+'.o')
  r=subprocess.run([os.environ['VOMAR_REAL_GCC'],*common,*flags,'-c',source,'-o',str(obj)])
  if r.returncode:raise SystemExit(r.returncode)
  objects[source]=str(obj)
 args=[objects.get(a,a) for a in args];extra=list(directory.glob('*.gcno'))
result=subprocess.run([os.environ['VOMAR_REAL_GCC'],*common,*args])
if result.returncode==0:
 out=Path(args[args.index('-o')+1]).absolute() if '-o' in args else Path.cwd()/'a.out'
 for path in [*out.parent.glob('*.gcno'),*extra]:
  if path.stat().st_mtime>=started-2:
   target=profile/str(path.resolve()).lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
raise SystemExit(result.returncode)
'''
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();output=a.output.resolve();output.mkdir(parents=True,exist_ok=False);profile=output/'profiles';profile.mkdir(parents=True,exist_ok=True);bin_dir=output/'bin';bin_dir.mkdir(exist_ok=True);wrapper=bin_dir/'gcc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755);(bin_dir/'cc').write_text(WRAPPER);(bin_dir/'cc').chmod(0o755)
 env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),'VOMAR_C_PROFILE':str(profile),'VOMAR_C_SOURCE_ROOT':str(ROOT/'firmware'),'PATH':str(bin_dir)+os.pathsep+os.environ['PATH']}
 subprocess.run([sys.executable,'-m','pytest','tools/firmware/tests','tools/hardware/tests','tools/android/tests','-q'],cwd=ROOT,env=env,check=True)
 data=list(profile.rglob('*.gcda'))
 if not data:raise ValueError('No actual native execution coverage was recorded')
 executed=output/'executed';executed.mkdir(exist_ok=True)
 for path in data:
  notes=matching_notes(path,profile)
  for source in (path,notes):
   relative=path.relative_to(profile) if source==path else path.relative_to(profile).with_suffix('.gcno')
   dest=executed/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
 subprocess.run([sys.executable,'-m','gcovr','--root',str(ROOT),'--filter',str(ROOT/'firmware')+'/','--include-internal-functions','--sonarqube',str(output/'c-coverage.xml'),str(executed)],check=True,cwd=ROOT)
if __name__=='__main__':main()
