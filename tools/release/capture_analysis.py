"""Export build analysis data, never credentials or executable helper code."""
import argparse,json,shlex,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);rows=[];mapping={}
 build=a.build.resolve();namespace=build.relative_to(ROOT) if build.is_relative_to(ROOT) else Path('_test/ci-firmware')
 def public_path(path):
  path=Path(path).resolve()
  return path.relative_to(ROOT) if path.is_relative_to(ROOT) else namespace/path.relative_to(build)
 def portable(arg):return arg.replace(str(build)+'/',str(ROOT/namespace)+'/').replace(str(build),str(ROOT/namespace)) if not build.is_relative_to(ROOT) else arg
 for db in a.build.rglob('compile_commands.json'):
  for row in json.loads(db.read_text()):
   f=Path(row['file']).resolve()
   canonical=f
   if not f.is_relative_to(ROOT/'firmware') and f.is_relative_to(a.build.resolve()):
    ancestors=list(f.parents)
    owners=[p for p in ancestors if p.name=='firmware']
    if owners:
     candidate=ROOT/'firmware'/f.relative_to(owners[0])
     if candidate.is_file() and candidate.read_bytes()==f.read_bytes():canonical=candidate
   if canonical.is_relative_to(ROOT/'firmware'):
    if canonical!=f:mapping[str(public_path(f))]=str(canonical.relative_to(ROOT))
    args=row.get('arguments') or shlex.split(row['command'])
    if any((x.startswith(('-fplugin','-specs','--specs','-B','-wrapper','@')) and x!='-specs=picolibc.specs') or x in ('|',';','&&') for x in args):raise ValueError('Unsupported compiler invocation for credentialed analysis')
    args=[str(canonical) if v==str(f) else portable(v) for v in args]
    rows.append({'directory':portable(row['directory']),'file':str(canonical),'arguments':args})
 for path in a.build.rglob('*'):
  if path.is_file() and path.suffix in ('.c','.h','.inc'):
   owners=[p for p in path.resolve().parents if p.name=='firmware']
   if owners:
    candidate=ROOT/'firmware'/path.resolve().relative_to(owners[0])
    if candidate.is_file() and candidate.read_bytes()==path.read_bytes():mapping[str(public_path(path))]=str(candidate.relative_to(ROOT))
  if path.is_file() and path.suffix in ('.h','.inc'):
   dest=a.output/'build-inputs'/public_path(path);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
 if not rows:raise ValueError('No real product C compilation was captured')
 (a.output/'source-map.json').write_text(json.dumps(mapping,indent=2)+'\n')
 (a.output/'compile_commands.json').write_text(json.dumps(rows)+'\n');(a.output/'build-context.json').write_text(json.dumps({'workspace':str(ROOT)}))
if __name__=='__main__':main()
