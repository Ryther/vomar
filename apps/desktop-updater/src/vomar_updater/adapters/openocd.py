"""Exclusive local OpenOCD Tcl RPC adapter with a finite nRF52840 write surface."""
from __future__ import annotations
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
from vomar_updater.core.installation import identity,FLASH,PAGE


def tcl_quote(value):
    value=str(value)
    if any(ord(c)<32 for c in value):raise ValueError('Control character in tool path')
    return '"'+value.replace('\\','/').replace('"','\\"').replace('$','\\$').replace('[','\\[').replace(']','\\]')+'"'


class OpenOcdProbe:
    def __init__(self,serial,executable=None):
        if not isinstance(serial,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,80}',serial):raise ValueError('Explicit DK serial required')
        self.serial=serial;self.executable=executable or shutil.which('openocd')
        if not self.executable:raise ValueError('OpenOCD is unavailable. Install the documented DK driver/tool package.')
        self.version=subprocess.run([str(self.executable),'--version'],capture_output=True,text=True,check=True).stderr.splitlines()[0]
        self.generation=secrets.token_hex(24);self.process=None;self.sock=None;self.halted=False;self.lock=threading.RLock();self.temp=None;self.resource=None
    def connect(self):
        # Start only after the UI has reviewed the named probe. No reset/halt here.
        if self.process is not None:raise ValueError('Probe lease already opened')
        from platformdirs import user_runtime_path
        from .locking import FileLease
        self.resource=FileLease(user_runtime_path('vomar')/('probe-'+self.serial+'.lock')).acquire()
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        self.temp=tempfile.TemporaryDirectory(prefix='vomar-openocd-');base=Path(self.temp.name);config=base/'probe.cfg'
        config.write_text(f'bindto 127.0.0.1\ntcl_port {port}\ngdb_port disabled\ntelnet_port disabled\nsource [find interface/jlink.cfg]\nadapter serial {tcl_quote(self.serial)}\ntransport select swd\nadapter speed 100\nsource [find target/nrf52.cfg]\nreset_config none\ncortex_m reset_config sysresetreq\ninit\n')
        self.log=(base/'openocd.log').open('wb')
        self.process=subprocess.Popen([str(self.executable),'-f',str(config)],stdout=self.log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+12
        try:
            while time.monotonic()<deadline:
                if self.process.poll() is not None:raise ConnectionError('DK connection failed. Check driver, serial, target power and SWD wiring.')
                try:self.sock=socket.create_connection(('127.0.0.1',port),timeout=1);self.sock.settimeout(10);return self.identity()
                except ConnectionRefusedError:time.sleep(.1)
            raise TimeoutError('DK connection timed out')
        except BaseException:self.close();raise
    def rpc(self,command):
        with self.lock:
            if self.sock is None:raise ConnectionError('Probe disconnected; no automatic reconnect')
            self.sock.sendall(command.encode('utf-8')+b'\x1a');out=bytearray()
            while True:
                b=self.sock.recv(65536)
                if not b:raise ConnectionError('DK connection lost; retain target HALT')
                out.extend(b)
                if len(out)>4*1024*1024:raise ValueError('Probe response bound')
                if out.endswith(b'\x1a'):return out[:-1].decode('utf-8')
    def read(self,address,size):
        if type(address) is not int or type(size) is not int or size<0 or size>FLASH or not ((0<=address<=FLASH-size) or (0x10000000<=address<=0x10001000+PAGE-size) or (0x40010000<=address<=0x40010510-size)):raise ValueError('Read outside admitted FLASH/FICR/UICR/watchdog region')
        data=bytearray()
        for off in range(0,size,512):
            count=min(512,size-off);result=self.rpc(f'read_memory {address+off} 8 {count}')
            try:values=[int(x,0) for x in result.split()]
            except ValueError as e:raise ValueError('Probe memory read failed') from e
            if len(values)!=count or any(not 0<=v<=255 for v in values):raise ValueError('Short/invalid probe memory read')
            data.extend(values)
        return bytes(data)
    def identity(self):return identity(self.read(0x10000000,PAGE))
    def halt(self,expected,watchdog_policy=None):
        from vomar_updater.core.installation import watchdog
        self.check(expected);watchdog(self.watchdog(),watchdog_policy);result=self.rpc('halt 2000')
        if self.rpc('nrf52.cpu curstate').strip()!='halted':raise ValueError('CPU did not halt')
        self.halted=True;self.check(expected)
    def check(self,expected):
        if self.process is None or self.process.poll() is not None or self.identity()!=expected:raise ValueError('Probe lease or live target changed')
        if self.halted and self.rpc('nrf52.cpu curstate').strip()!='halted':raise ValueError('Target unexpectedly left HALT')
    def watchdog(self):
        def w(at):return struct.unpack('<I',self.read(at,4))[0]
        return {'runStatus':w(0x40010400),'config':w(0x4001050c),'crv':w(0x40010504),'rren':w(0x40010508)}
    def _ready(self):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            raw=self.rpc('read_memory 0x4001e400 32 1').strip()
            try:
                if int(raw,0)==1:return
            except ValueError:raise ValueError('Invalid NVMC ready response')
            time.sleep(.001)
        raise TimeoutError('NVMC completion uncertain; retain HALT')
    def _write(self,address,words):
        result=self.rpc(f'write_memory {address} 32 {{'+ ' '.join(str(w) for w in words)+'}')
        if result.strip():raise ValueError('Probe write did not complete cleanly')
    def erase_page(self,address,expected):
        if type(address) is not int or address%PAGE or not 0<=address<=FLASH-PAGE:raise ValueError('Only aligned FLASH page erasure is admitted')
        with self.lock:
            self.check(expected)
            if not self.halted:raise ValueError('Exclusive HALT required')
            self._ready();self._write(0x4001e504,[2]);self._ready();self._write(0x4001e508,[address]);self._ready();self._write(0x4001e504,[0]);self._ready()
    def program(self,address,data,expected):
        if type(address) is not int or address%4 or not isinstance(data,bytes) or not 4<=len(data)<=256 or len(data)%4 or not 0<=address<=FLASH-len(data) or address//PAGE!=(address+len(data)-1)//PAGE:raise ValueError('Only bounded aligned FLASH word batches are admitted')
        with self.lock:
            self.check(expected)
            if not self.halted:raise ValueError('Exclusive HALT required')
            self._ready();self._write(0x4001e504,[1]);self._ready()
            for offset in range(0,len(data),4):self._write(address+offset,[struct.unpack_from('<I',data,offset)[0]]);self._ready()
            self._write(0x4001e504,[0]);self._ready()
    def start(self):
        if not self.halted:raise ValueError('Explicit verified halted target required')
        self._ready();self.rpc('reset run');self.halted=False
    def close(self):
        # Only host resources: shutdown has no resume/reset command. Preserve the
        # target's last state even if Tcl shutdown cannot be acknowledged.
        if self.sock:
            try:self.sock.sendall(b'shutdown\x1a')
            except OSError:pass
            self.sock.close();self.sock=None
        if self.process:
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)
            self.process=None
        if hasattr(self,'log'):self.log.close()
        if self.temp:self.temp.cleanup();self.temp=None
        if self.resource:self.resource.close();self.resource=None
