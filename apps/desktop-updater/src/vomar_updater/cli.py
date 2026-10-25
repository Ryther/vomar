"""Vomar CLI. Hardware mutation always has a fresh interactive review."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys
from . import __version__
from .service import Service


def parser():
    p=argparse.ArgumentParser(prog='vomar',description=__doc__);p.add_argument('--version',action='version',version=__version__);p.add_argument('--state',type=Path,help='Private application state directory')
    groups=p.add_subparsers(dest='group',required=True)
    commands={'releases':['inspect','latest','verify'],'devices':['list','scan','import','save','remove'],'sessions':['list','details','confirm'],'diagnostics':['read','export'],'updates':['preview','run','resume','prepare'],'backup':['capture','import'],'first-install':['run'],'repair':['run'],'start':['run'],'probe':['inspect','halt'],'mqtt':['save','connect','disconnect','devices'],'settings':['get','save'],'trial':['preview','run'],'zigbee':['preview','run','reconcile'],'fleet':['list','preview','run'],'bench':['install','repair','start']}
    for group,actions in commands.items():
        q=groups.add_parser(group);sub=q.add_subparsers(dest='action',required=True)
        for action in actions:
            r=sub.add_parser(action)
            for name in ('path','package','target','serial','session','original','export','repository','name','room','id','ieee','network','uri','username','theme','language','source','public-key','mode'):
                r.add_argument('--'+name)
            r.add_argument('--topic',action='append',default=[],help='MQTT base topic; repeat at most three times');r.add_argument('--allow-plaintext',action='store_true')
    return p


def confirm(review):
    print(json.dumps(review,indent=2),file=sys.stderr)
    if not sys.stdin.isatty():raise ValueError('Mutation needs an interactive terminal and a fresh review; no yes/bypass option exists')
    answer=input('To approve this operation, type '+review['challenge']+': ')
    if answer!=review['challenge']:raise ValueError('Operation not approved')


async def run(args):
    if args.group=='releases' and args.action=='verify':
        from .core.packages import inspect_package
        if not args.path or not args.public_key:raise ValueError('--path and --public-key are required for read-only development verification')
        p=inspect_package(Path(args.path).read_bytes(),Path(args.public_key).read_bytes());return {'schema':p.schema,'version':p.version,'digest':p.digest,'adoptedForDeviceUse':False}
    service=Service(args.state,on_event=lambda e:print(json.dumps({'event':e}),file=sys.stderr))
    a={k:v for k,v in vars(args).items() if v is not None};group=args.group;action=args.action
    try:
        if group=='mqtt' and action=='save':
            if args.username:
                import getpass
                a['password']=getpass.getpass('Broker password (OS credential store): ')
            a['networks']=[{'id':f'network-{i+1}','label':f'Network {i+1}','topic':t} for i,t in enumerate(args.topic)]
        if group in ('trial','bench'):
            if not args.path:raise ValueError('--path is required for a separate qualification candidate')
            await service.dispatch('trial.inspect',{'path':args.path})
        if args.package:await service.dispatch('releases.inspect',{'path':args.package})
        if group in ('first-install','repair','start','bench') or group=='backup' and action=='capture' or group=='probe' and action=='halt':
            if not args.serial:raise ValueError('--serial is required for an explicitly selected DK')
            r=await service.dispatch('probe.inspect',{**a,'candidate':group=='bench'});confirm(r);await service.dispatch('execute',r)
            if group=='probe':return {'targetHalted':True}
            if args.original:await service.dispatch('backup.import',{'path':args.original})
            elif group in ('first-install','backup') or group=='bench' and action=='install':
                path=args.export or args.path
                if not path:raise ValueError('--export is required to preserve and reopen the protected original')
                await service.dispatch('backup.capture',{'path':path})
            else:raise ValueError('--original is required; never replace the preserved original after interruption')
            if group=='backup':return {'original':service.original.digest,'export':service.export_path}
            r=await service.dispatch(('bench.preview' if action=='install' else 'bench.'+action+'-preview') if group=='bench' else group+'.preview',a);confirm(r);return await service.dispatch('execute',r)
        if group=='zigbee' or group=='mqtt' and action=='devices':
            await service.dispatch('mqtt.connect');await asyncio.sleep(.5)
        if group=='updates' and action in ('resume','prepare'):
            r=await service.dispatch('updates.resume-preview' if action=='resume' else 'updates.prepare-preview',a);confirm(r);return await service.dispatch('execute',r)
        if group in ('updates','trial','zigbee','fleet') and action=='run':
            r=await service.dispatch(group+'.preview',a);confirm(r);return await service.dispatch('execute',r)
        result=await service.dispatch(group+'.'+action,a)
        if isinstance(result,dict) and 'review' in result and group=='sessions':confirm(result);return await service.dispatch('execute',result)
        return result
    finally:await service.close()


def main(argv=None):
    args=parser().parse_args(argv)
    try:result=asyncio.run(run(args));print(json.dumps(result,indent=2));return 0
    except (ValueError,KeyError,OSError,RuntimeError) as e:
        print(json.dumps({'error':str(e),'operationStartedAutomatically':False}),file=sys.stderr);return 2
    except KeyboardInterrupt:
        print('Stopped. Review preserved session state before another attempt.',file=sys.stderr);return 130

if __name__=='__main__':raise SystemExit(main())
