#!/usr/bin/env python3
"""Serve English slices on loopback and save explicit imports locally."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
from pathlib import Path
import threading
from urllib.parse import urlsplit
from build_data import page
from library import ROOT, MAX_BYTES, read_json, normalize_library, load_starter, parse_import, merge_library, atomic_save

class LibraryStore:
    def __init__(self,data_dir):
        self.path=Path(data_dir)/'library.json';self.lock=threading.Lock()
        if self.path.parent.is_symlink():raise ValueError('data directory cannot be symbolic')
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.parent.is_symlink():raise ValueError('data directory cannot be symbolic')
        self.lock_path=self.path.parent/'.server.lock'
        try:self.lock_fd=os.open(self.lock_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:raise ValueError('data directory is locked; confirm the other service has stopped before removing a stale .server.lock') from None
        os.write(self.lock_fd,str(os.getpid()).encode())
    def release(self):
        if hasattr(self,'lock_fd'):
            os.close(self.lock_fd)
            try:self.lock_path.unlink()
            except FileNotFoundError:pass
    def get(self):
        return normalize_library(read_json(self.path)) if self.path.exists() or self.path.is_symlink() else load_starter()
    def update(self,operation,payload):
        with self.lock:
            library=self.get()
            if operation=='import':library=merge_library(library,parse_import(payload.get('text'),payload.get('format','auto')))
            elif operation=='progress':
                identifier=payload.get('id');seen=payload.get('seen')
                if not isinstance(identifier,str) or not isinstance(seen,bool):raise ValueError('invalid progress update')
                known={x['id'] for x in library['words']+library['phrases']}
                if identifier not in known:raise ValueError('unknown entry')
                values=set(library['progress']['seen'])
                if seen:values.add(identifier)
                else:values.discard(identifier)
                library['progress']['seen']=sorted(values)
            else:raise ValueError('unknown operation')
            atomic_save(self.path,library);return library

def make_handler(store,parent_origin=''):
    class Handler(BaseHTTPRequestHandler):
        server_version='EnglishSlices/0.1'
        def log_message(self,*args):pass
        def valid_host(self):return self.headers.get('Host','') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        def reply(self,status,value,ctype='application/json; charset=utf-8'):
            raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if not self.valid_host():return self.reply(403,{'error':'invalid host'})
            route=urlsplit(self.path).path
            try:
                if route in ('/','/index.html'):
                    return self.reply(200,page(service_mode=True,parent_origin=parent_origin).encode(),'text/html; charset=utf-8')
                if route in ('/api/library','/api/export'):
                    data=store.get();return self.reply(200,{'library':data,'storage':'local-file'})
                return self.reply(404,{'error':'not found'})
            except (OSError,ValueError,UnicodeError):return self.reply(500,{'error':'local data could not be read; no file was changed'})
        def do_POST(self):
            if not self.valid_host():return self.reply(403,{'error':'invalid host'})
            expected='http://'+self.headers.get('Host','')
            if self.headers.get('Origin') not in (None,expected) or self.headers.get('X-Workhub-Request')!='1':return self.reply(403,{'error':'same-origin request required'})
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json' or self.headers.get('Transfer-Encoding'):return self.reply(415,{'error':'JSON body required'})
            try:length=int(self.headers.get('Content-Length',''))
            except ValueError:return self.reply(411,{'error':'content length required'})
            if not 0<length<=2*MAX_BYTES+4096:return self.reply(413,{'error':'request exceeds limit'})
            route=urlsplit(self.path).path
            operation={'/api/import':'import','/api/progress':'progress'}.get(route)
            if not operation:return self.reply(404,{'error':'not found'})
            try:
                self.connection.settimeout(5);raw=self.rfile.read(length)
                if len(raw)!=length:raise ValueError('incomplete body')
                payload=json.loads(raw)
                if not isinstance(payload,dict):raise ValueError('body must be an object')
                data=store.update(operation,payload);return self.reply(200,{'library':data,'storage':'local-file'})
            except (ValueError,UnicodeError,TypeError):return self.reply(400,{'error':'invalid import or progress; check the file format, size and fields'})
            except (OSError,TimeoutError):return self.reply(500,{'error':'local save failed; do not assume changes were saved'})
    return Handler

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8831);parser.add_argument('--data-dir',type=Path,default=ROOT/'data');parser.add_argument('--parent-origin',default='')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('invalid port')
    try:
        store=LibraryStore(args.data_dir);store.get();page(parent_origin=args.parent_origin)
        server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(store,args.parent_origin));server.daemon_threads=True
        try:store.acquire()
        except (OSError,ValueError):server.server_close();raise
    except (OSError,ValueError) as exc:parser.error(str(exc))
    print(f'English slices: http://127.0.0.1:{server.server_port}/',flush=True)
    def terminate(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();store.release()
if __name__=='__main__':main()
