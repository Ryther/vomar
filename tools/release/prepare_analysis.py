"""Protected baseline validation/remapping of analysis data; no compiler execution."""
import argparse,json,shutil
from pathlib import Path,PurePosixPath
from .reports import check

def prepare(reports,candidate,sha):
 reports=Path(reports).resolve();candidate=Path(candidate).resolve();check(reports,sha)
 if any(p.is_symlink() for p in reports.rglob('*')):raise ValueError('Analysis artifacts cannot contain symlinks')
 context=json.loads((reports/'build-context.json').read_text());old=context['workspace']
 if not isinstance(old,str) or not old.startswith('/') or '..' in PurePosixPath(old).parts:raise ValueError('Invalid analysis workspace')
 for p in (reports/'build-inputs').rglob('*'):
  if p.is_file():
   rel=p.relative_to(reports/'build-inputs')
   if rel.parts[:2]!=('_test','ci-firmware') or p.suffix not in ('.h','.inc'):raise ValueError('Unsupported generated analysis input')
   dest=candidate/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
 rows=json.loads((reports/'compile_commands.json').read_text())
 def remap(text):
  # Arguments such as -I/path and --sysroot=/path are individual data strings,
  # never shell commands. Replace their exact workspace prefix as well.
  return text.replace(old+'/',str(candidate)+'/') if text!=old else str(candidate)
 for row in rows:
  if set(row)!={'file','directory','arguments'} or not row['file'].startswith(old+'/firmware/') or '..' in PurePosixPath(row['file']).parts:raise ValueError('Compilation scope is not first-party firmware')
  args=row['arguments']
  if type(args) is not list or not args or any(not isinstance(x,str) or '\x00' in x or (x.startswith(('-fplugin','-specs','--specs','-B','-wrapper','@')) and x!='-specs=picolibc.specs') or x in ('|',';','&&') for x in args):raise ValueError('Unsafe compiler metadata')
  # The scanner reads this database; no candidate compiler path is admitted.
  if Path(args[0]).name not in ('arm-zephyr-eabi-gcc','arm-zephyr-eabi-g++'):raise ValueError('Unexpected target compiler identity')
  row['file']=remap(row['file']);row['directory']=remap(row['directory']);row['arguments']=[remap(x) for x in args]
 (reports/'compile_commands.json').write_text(json.dumps(rows)+'\n')
 for name in ('python-coverage.xml','lcov.info','c-coverage.xml'):
  path=reports/name
  if path.is_file():path.write_text(path.read_text().replace(old,str(candidate)))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--reports',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--sha',required=True);a=p.parse_args();prepare(a.reports,a.candidate,a.sha)
