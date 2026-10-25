"""Public GitHub distribution discovery; signed-package validation stays independent."""
from __future__ import annotations
import re
import urllib.parse
import urllib.request
from tools.release.manifest import loads,validate,digest

ALLOWED={'api.github.com','github.com','objects.githubusercontent.com','release-assets.githubusercontent.com'}


def repository(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',value):raise ValueError('Use a public GitHub owner/repository')
    return value


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        allowed_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)


def allowed_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname not in ALLOWED or p.username or p.password or p.fragment or p.port not in (None,443):raise ValueError('Unexpected public GitHub asset URL')


def download(url,limit):
    allowed_url(url)
    request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json, application/octet-stream','User-Agent':'Vomar-Updater'})
    with urllib.request.build_opener(Redirect()).open(request,timeout=20) as r:
        if int(r.headers.get('Content-Length','0'))>limit:raise ValueError('Download exceeds supported bound')
        result=r.read(limit+1)
        if len(result)>limit:raise ValueError('Download exceeds supported bound')
        return result


def select(release,manifest,repo):
    repository(repo);validate(manifest)
    if release.get('draft') is not False or release.get('prerelease') is not False or release.get('tag_name')!=manifest['tag']:raise ValueError('A matching stable published distribution is required')
    assets=release.get('assets')
    if type(assets) is not list or len(assets)>64:raise ValueError('Invalid GitHub assets')
    names=[a.get('name') for a in assets]
    if len(set(names))!=len(names):raise ValueError('Duplicate GitHub asset name')
    result={}
    for a in manifest['artifacts']:
        matches=[r for r in assets if r.get('name')==a['filename']]
        if len(matches)!=1 or type(matches[0].get('size')) is not int or matches[0]['size']!=a['size']:raise ValueError('Missing or size-mismatched distribution asset')
        url=matches[0].get('browser_download_url','');allowed_url(url)
        parsed=urllib.parse.urlsplit(url)
        if parsed.hostname!='github.com' or parsed.path!=f'/{repo}/releases/download/{manifest["tag"]}/{a["filename"]}':raise ValueError('Asset is not bound to selected repository/tag')
        result[a['role']]={**a,'url':url}
    from tools.firmware.package_android_update import MAX_ZIP
    if not 1<=result['firmware-common']['size']<=MAX_ZIP:raise ValueError('Firmware asset exceeds the signed package bound')
    if result['firmware-common']['filename']!=f'vomar-firmware-{manifest["distributionVersion"]}.zip':raise ValueError('Noncanonical firmware asset')
    return result


def latest(repo,fetch=download):
    repo=repository(repo);release=loads(fetch(f'https://api.github.com/repos/{repo}/releases/latest',2*1024*1024))
    matches=[a for a in release.get('assets',[]) if a.get('name')=='release-manifest.json' and type(a.get('size')) is int and 0<a['size']<=65536]
    if len(matches)!=1:raise ValueError('Missing or ambiguous distribution manifest; import a signed local package')
    url=matches[0]['browser_download_url'];allowed_url(url)
    if urllib.parse.urlsplit(url).path!=f'/{repo}/releases/download/{release.get("tag_name")}/release-manifest.json':raise ValueError('Unexpected manifest URL')
    raw=fetch(url,65536)
    if len(raw)!=matches[0]['size']:raise ValueError('Manifest asset size mismatch')
    manifest=loads(raw);return manifest,select(release,manifest,repo)


def acquire(asset,fetch=download):
    raw=fetch(asset['url'],asset['size'])
    if len(raw)!=asset['size'] or digest(raw)!=asset['sha256']:raise ValueError('Downloaded asset bytes differ from distribution manifest')
    return raw
