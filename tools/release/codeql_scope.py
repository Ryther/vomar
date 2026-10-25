"""Verify extracted product source presence and map byte-identical build snapshots."""
import argparse,json
from pathlib import Path
import urllib.parse,zipfile
ROOT=Path(__file__).resolve().parents[2]
REFERENCE_ONLY={
 'firmware/research/src/main.c':'Standalone research harness; not a distribution image',
 'firmware/ota_migration/src/legacy_bridge_entry_zephyr.c':'Historical device-specific bridge entry; current common migration is separately required',
}

def check_archive(archive,root=ROOT):
    required={str(p.relative_to(root)) for p in (root/'firmware').rglob('*.c')}-REFERENCE_ONLY.keys()
    with zipfile.ZipFile(archive) as z:names=z.namelist()
    missing=[p for p in required if not any(n.endswith('/'+p) or n==p for n in names)]
    if missing:raise ValueError('CodeQL did not archive required product C sources: '+', '.join(sorted(missing)))
    return {'required':sorted(required),'referenceOnly':REFERENCE_ONLY}


def remap(directory,mapping):
    def visit(value):
        if isinstance(value,dict):
            if isinstance(value.get('uri'),str):
                raw=urllib.parse.unquote(value['uri'])
                if raw in mapping:value['uri']=urllib.parse.quote(mapping[raw],safe='/')
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    for p in Path(directory).glob('*.sarif'):
        data=json.loads(p.read_text());visit(data);p.write_text(json.dumps(data)+'\n')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--reports',type=Path,required=True);p.add_argument('--sarif',type=Path,required=True);a=p.parse_args()
 result=check_archive(a.archive);mapping=json.loads((a.reports/'source-map.json').read_text());remap(a.sarif,mapping);(a.reports/'codeql-source-scope.json').write_text(json.dumps(result,indent=2)+'\n')
