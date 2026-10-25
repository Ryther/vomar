"""Durable private object store and SQLite journal; never persists consent."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from ..adapters.filesystem import publish_new,sync_directory,ensure_directory


def sha(raw):return hashlib.sha256(raw).hexdigest()



class Store:
    def __init__(self,root):
        self.root=Path(root).absolute()
        if self.root.is_symlink():raise ValueError('Private state cannot be a symlink')
        ensure_directory(self.root)
        self.objects=self.root/'objects';ensure_directory(self.objects)
        if self.objects.is_symlink():raise ValueError('Object directory link forbidden')
        if (self.root/'sessions.sqlite').is_symlink():raise ValueError('Session database link forbidden')
        self.db=sqlite3.connect(self.root/'sessions.sqlite',timeout=5)
        self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        current=self.db.execute('PRAGMA user_version').fetchone()[0]
        if current not in (0,1):raise ValueError('Unsupported session database version')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS objects(digest TEXT PRIMARY KEY,kind TEXT NOT NULL,size INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,binding TEXT NOT NULL,phase TEXT NOT NULL,uncertain INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(session TEXT REFERENCES sessions(id),sequence INTEGER,phase TEXT,detail TEXT,previous TEXT NOT NULL,head TEXT NOT NULL,PRIMARY KEY(session,sequence));
CREATE TABLE IF NOT EXISTS receipts(digest TEXT,path TEXT,measured TEXT,PRIMARY KEY(digest,path));
CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,record TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY,value TEXT NOT NULL);
PRAGMA user_version=1;''')
        if 'head' not in {row[1] for row in self.db.execute('PRAGMA table_info(events)')}:raise ValueError('Pre-release journal schema requires read-only export; mutation admission refused')
        if os.name!='nt':os.chmod(self.root/'sessions.sqlite',0o600)
    def close(self):self.db.close()
    def path(self,key):
        if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key):raise ValueError('Object digest required')
        p=self.objects/key
        if p.is_symlink():raise ValueError('Object link forbidden')
        return p
    def put(self,raw,kind):
        if not isinstance(raw,bytes) or kind not in ('package','original','carrier'):raise ValueError('Immutable typed object required')
        key=sha(raw);dest=self.path(key)
        if dest.exists():
            if dest.read_bytes()!=raw:raise ValueError('Immutable object corrupted')
        else:
            temp=self.objects/('.'+uuid.uuid4().hex)
            try:
                fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as f:
                    f.write(raw);f.flush();os.fsync(f.fileno())
                try:publish_new(temp,dest)
                except FileExistsError:
                    if dest.read_bytes()!=raw:raise ValueError('Object publication collision')
                sync_directory(self.objects)
                if dest.read_bytes()!=raw:raise ValueError('Published object was not complete')
            finally:temp.unlink(missing_ok=True)
        with self.db:self.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',(key,kind,len(raw)))
        return key
    def get(self,key):
        data=self.path(key).read_bytes()
        if sha(data)!=key:raise ValueError('Stored object was modified')
        return data
    def export(self,key,path):
        path=Path(path);raw=self.get(key)
        temp=path.parent/('.vomar-export-'+uuid.uuid4().hex)
        try:
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:
                f.write(raw);f.flush();os.fsync(f.fileno())
            publish_new(temp,path);sync_directory(path.parent)
        finally:temp.unlink(missing_ok=True)
        if not self.reopen_receipt(key,path):raise ValueError('Export reopen mismatch')
        return path
    def reopen_receipt(self,key,path):
        p=Path(path)
        okay=not p.is_symlink() and p.is_file() and sha(p.read_bytes())==key and p.read_bytes()==self.get(key)
        if okay:
            with self.db:self.db.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?)',(key,str(p.absolute()),key))
        return okay
    def begin(self,binding):
        if 'consent' in binding:raise ValueError('Consent must remain process-local')
        session=uuid.uuid4().hex
        with self.db:self.db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(session,json.dumps(binding,sort_keys=True),'prepared',0,time.time()))
        return session
    def record(self,session,phase,detail=None):
        detail=detail or {}
        if 'consent' in detail:raise ValueError('Consent must remain process-local')
        with self.db:
            row=self.db.execute('SELECT uncertain,binding FROM sessions WHERE id=?',(session,)).fetchone()
            if row is None:raise ValueError('Unknown session')
            seq=self.db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE session=?',(session,)).fetchone()[0]
            uncertain=row[0] or phase.endswith('-intent')
            if phase in ('verified','operator-confirmed'):uncertain=False
            prior=self.db.execute('SELECT head FROM events WHERE session=? ORDER BY sequence DESC LIMIT 1',(session,)).fetchone()
            previous=prior[0] if prior else sha(row[1].encode())
            encoded=json.dumps(detail,sort_keys=True)
            head=sha(json.dumps([session,seq,phase,encoded,previous],separators=(',',':')).encode())
            self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(session,seq,phase,encoded,previous,head))
            self.db.execute('UPDATE sessions SET phase=?,uncertain=? WHERE id=?',(phase,int(uncertain),session))
    def sessions(self):
        return [{'id':i,'binding':json.loads(b),'phase':p,'uncertain':bool(u),'created':t} for i,b,p,u,t in self.db.execute('SELECT * FROM sessions ORDER BY created DESC')]
    def events(self,session):
        row=self.db.execute('SELECT binding FROM sessions WHERE id=?',(session,)).fetchone()
        if row is None:raise ValueError('Unknown journal session')
        previous=sha(row[0].encode());result=[]
        for seq,phase,detail,prior,head in self.db.execute('SELECT sequence,phase,detail,previous,head FROM events WHERE session=? ORDER BY sequence',(session,)):
            measured=sha(json.dumps([session,seq,phase,detail,previous],separators=(',',':')).encode())
            if seq!=len(result)+1 or prior!=previous or head!=measured:raise ValueError('Session journal integrity/order failed; no repair authority')
            result.append({'sequence':seq,'phase':phase,'detail':json.loads(detail)});previous=head
        return result
    def setting(self,name,value=None):
        if value is None:
            row=self.db.execute('SELECT value FROM settings WHERE name=?',(name,)).fetchone();return json.loads(row[0]) if row else None
        with self.db:self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(name,json.dumps(value)))
        return value
