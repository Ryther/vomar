"""Read native component version owners without resetting them to distribution."""
import argparse,json,subprocess,tomllib
from pathlib import Path
from .assemble import android_owner
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();v,c=android_owner((ROOT/'apps/android-updater/app/build.gradle.kts').read_text())
 value={'distributionVersion':(ROOT/'VERSION').read_text().strip(),'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'android':{'version':v,'versionCode':c},'desktop':{'version':tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']},'zigbee2mqtt':{'version':json.loads((ROOT/'integrations/zigbee2mqtt/package.json').read_text())['version']}}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(value,indent=2)+'\n')
if __name__=='__main__':main()
