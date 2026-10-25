"""Default-off typed runtime refuses weaker target/stack/auth configurations."""
from pathlib import Path
import subprocess,pytest
ROOT=Path(__file__).resolve().parents[3]
GOOD=dict(CONFIG_VIMAR_LOADER_RUNTIME_V2=1,CONFIG_SOC_NRF52840=1,CONFIG_VIMAR_OTA_SPLIT_STAGING=1,CONFIG_PSA_WANT_ALG_SHA_256=1,CONFIG_VIMAR_P031_PROTECTION=1,CONFIG_MAIN_STACK_SIZE=12288,CONFIG_MCUMGR_TRANSPORT_BT=1,CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN=1,CONFIG_MCUMGR_TRANSPORT_WORKQUEUE_STACK_SIZE=8192,VIMAR_LOADER_CONTRACT_BINDINGS_HEADER='"explicit.h"')

def compile(tmp_path,values):
 src=tmp_path/'guard.c';src.write_text('#include "loader_runtime_config.h"\nint main(void){return 0;}\n')
 return subprocess.run(['cc','-std=c11','-Werror','-I'+str(ROOT/'firmware/loader_contract'),*[f'-D{k}={v}' for k,v in values.items()],'-c',str(src),'-o',str(tmp_path/'guard.o')],capture_output=True,text=True)

def test_default_off_is_legacy_and_audited_optin_compiles(tmp_path):
 assert compile(tmp_path,{}).returncode==0
 assert compile(tmp_path,GOOD).returncode==0
 values=GOOD.copy();del values["CONFIG_MCUMGR_TRANSPORT_BT"];assert compile(tmp_path,values).returncode==0

@pytest.mark.parametrize('field',[k for k in GOOD if k not in ('CONFIG_VIMAR_LOADER_RUNTIME_V2','CONFIG_MCUMGR_TRANSPORT_BT')])
def test_each_target_resource_auth_and_authority_precondition_is_required(tmp_path,field):
 values=GOOD.copy();del values[field]
 assert compile(tmp_path,values).returncode!=0

@pytest.mark.parametrize('field,value',[('CONFIG_MAIN_STACK_SIZE',8192),('CONFIG_MCUMGR_TRANSPORT_WORKQUEUE_STACK_SIZE',4608)])
def test_known_legacy_stack_sizes_are_not_silently_reused(tmp_path,field,value):
 values=GOOD.copy();values[field]=value;assert compile(tmp_path,values).returncode!=0

@pytest.mark.parametrize('field',['CONFIG_MCUMGR_TRANSPORT_UART','CONFIG_MCUMGR_TRANSPORT_RAW_UART','CONFIG_MCUMGR_TRANSPORT_UART_ASYNC','CONFIG_MCUMGR_TRANSPORT_UDP','CONFIG_MCUMGR_TRANSPORT_SHELL','CONFIG_MCUMGR_TRANSPORT_LORAWAN','CONFIG_MCUMGR_TRANSPORT_DUMMY','CONFIG_MCUMGR_TRANSPORT_RAW_DUMMY','CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW','CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_ENCRYPT'])
def test_typed_read_identity_cannot_leak_through_unauthenticated_parallel_transport(tmp_path,field):
 values=GOOD.copy();values[field]=1;assert compile(tmp_path,values).returncode!=0
