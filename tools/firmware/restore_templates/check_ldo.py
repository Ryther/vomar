from pathlib import Path
import re,sys
for item in sys.argv[1:]:
 z=Path(item)/'zephyr';s=(z/'zephyr.dts').read_text();c=(z/'.config').read_text()
 reg1=re.search(r'\breg1:\s*regulator@40000578\s*\{([^}]+)\}',s,re.S)
 reg0=re.search(r'\breg0:\s*regulator@40000580\s*\{([^}]+)\}',s,re.S)
 assert reg1 and re.search(r'regulator-initial-mode\s*=\s*<\s*(?:0x0|0)\s*>',reg1[1]),f'{item}: REG1 inherits DC/DC mode'
 assert reg0 and re.search(r'status\s*=\s*"disabled"',reg0[1]),f'{item}: REG0 DC/DC enabled by DT status'
 assert 'CONFIG_SOC_DCDC_NRF52X=y' not in c and 'CONFIG_SOC_DCDC_NRF52X_HV=y' not in c
 print(f'PASS {item}: REG1 LDO; REG0 DC/DC disabled')
