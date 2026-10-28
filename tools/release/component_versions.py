"""Read native component version owners without resetting them to distribution."""
import argparse,json,re,subprocess,tomllib
from pathlib import Path
from .assemble import android_owner
ROOT=Path(__file__).resolve().parents[2]


def firmware_owner(text):
 rows=re.findall(r'^(VERSION_MAJOR|VERSION_MINOR|PATCHLEVEL|VERSION_TWEAK|EXTRAVERSION)[ \t]*=[ \t]*([^\r\n]*)$',text,re.M)
 if len(rows)!=5 or len(dict(rows))!=5:raise ValueError('Ambiguous native firmware version owner')
 fields=dict(rows)
 if fields['EXTRAVERSION'].strip() or fields['VERSION_TWEAK'].strip()!='0':raise ValueError('Distribution requires an exact native firmware release triple')
 values=[]
 for name,maximum in [('VERSION_MAJOR',255),('VERSION_MINOR',255),('PATCHLEVEL',65535)]:
  raw=fields[name].strip()
  if not re.fullmatch(r'0|[1-9][0-9]*',raw) or int(raw)>maximum:raise ValueError('Invalid native firmware version')
  values.append(raw)
 return '.'.join(values)

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();v,c=android_owner((ROOT/'apps/android-updater/app/build.gradle.kts').read_text())
 value={'distributionVersion':(ROOT/'VERSION').read_text().strip(),'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'firmware':{'version':firmware_owner((ROOT/'firmware/VERSION').read_text())},'android':{'version':v,'versionCode':c},'desktop':{'version':tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']},'zigbee2mqtt':{'version':json.loads((ROOT/'integrations/zigbee2mqtt/package.json').read_text())['version']}}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(value,indent=2)+'\n')
if __name__=='__main__':main()
