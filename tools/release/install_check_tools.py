"""Install checksum-verified read-only source-check tools on Linux CI."""
import argparse,json,tarfile
from pathlib import Path
from tools.dev.bootstrap import download,unpack
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);m=json.loads((ROOT/'tools/release/runtime-tools.json').read_text())
 for name in ('gitleaks','actionlint'):
  archive=a.output/(name+'.tar.gz');download(m[name],archive);unpack(archive,a.output);(a.output/name).chmod(0o755)
if __name__=='__main__':main()
