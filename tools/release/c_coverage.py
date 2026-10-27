"""Collect actual host C execution coverage from the existing Python native suites.

The compiler wrapper preserves generated harness sources and copies .gcno before
disposable test directories vanish; profile data is written outside those
directories. No device/toolchain execution or physical qualification follows.
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
import glob,os,shutil,subprocess,sys,tempfile,time,uuid
from pathlib import Path
args=sys.argv[1:]
if any(x in args for x in ('--version','-dumpversion','-dumpmachine','-print-search-dirs')):raise SystemExit(subprocess.call([os.environ['VOMAR_REAL_GCC'],*args]))
profile=Path(os.environ['VOMAR_C_PROFILE'])/uuid.uuid4().hex;profile.mkdir();started=time.time()
sources=[a for a in args if a.endswith(('.c','.S')) and not a.startswith('-')]
root=Path(os.environ.get('VOMAR_C_SOURCE_ROOT',os.getcwd())).resolve()
temporary=Path(tempfile.gettempdir()).resolve();snapshots={}
def preserve_directory(directory):
 original=Path(directory).resolve()
 if original.is_relative_to(root) or not original.is_relative_to(temporary) or original==temporary or not original.is_dir():return original
 if profile.is_relative_to(original):raise ValueError('Coverage snapshot cannot contain its output directory')
 if original not in snapshots:
  target=profile/'sources'/str(len(snapshots));shutil.copytree(original,target,symlinks=True)
  snapshots[original]=target
 return snapshots[original]
preserved={}
for source in sources:
 original=Path(source).resolve()
 preserved[source]=str(preserve_directory(original.parent)/original.name)
rewritten=[];index=0
while index<len(args):
 arg=args[index]
 if arg in ('-I','-iquote','-isystem','-include'):
  value=args[index+1]
  if arg=='-include':
   if Path(value).is_file():value=str(preserve_directory(Path(value).parent)/Path(value).name)
  else:value=str(preserve_directory(value))
  rewritten.extend([arg,value]);index+=2;continue
 if arg.startswith('-I') and len(arg)>2:arg='-I'+str(preserve_directory(arg[2:]))
 rewritten.append(arg);index+=1
args=rewritten
common=['--coverage','-fprofile-abs-path','-fprofile-dir='+str(profile)]
extra=[]
if len(sources)>1 and '-c' not in args and '-fsyntax-only' not in args:
 directory=profile/'objects';directory.mkdir();objects={}
 flags=[a for a in args if a not in sources]
 if '-o' in flags:
  index=flags.index('-o');del flags[index:index+2]
 for i,source in enumerate(sources):
  obj=directory/('unit'+str(i)+'.o')
  r=subprocess.run([os.environ['VOMAR_REAL_GCC'],*common,*flags,'-c',preserved[source],'-o',str(obj)])
  if r.returncode:raise SystemExit(r.returncode)
  objects[source]=str(obj)
 args=[objects.get(a,a) for a in args];extra=list(directory.glob('*.gcno'))
else:
 args=[preserved.get(a,a) for a in args]
result=subprocess.run([os.environ['VOMAR_REAL_GCC'],*common,*args])
if result.returncode==0:
 out=Path(args[args.index('-o')+1]).absolute() if '-o' in args else Path.cwd()/'a.out'
 for path in [*out.parent.glob('*.gcno'),*extra]:
  if path.stat().st_mtime>=started-2:
   target=profile/str(path.resolve()).lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
raise SystemExit(result.returncode)
'''
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();output=a.output.resolve();profile=output/'profiles';profile.mkdir(parents=True,exist_ok=True);bin_dir=output/'bin';bin_dir.mkdir(exist_ok=True);wrapper=bin_dir/'gcc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755);(bin_dir/'cc').write_text(WRAPPER);(bin_dir/'cc').chmod(0o755)
 env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),'VOMAR_C_PROFILE':str(profile),'VOMAR_C_SOURCE_ROOT':str(ROOT),'PATH':str(bin_dir)+os.pathsep+os.environ['PATH']}
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
