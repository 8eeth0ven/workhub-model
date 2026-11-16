"""Bounded word-list parsing and atomic local persistence. Standard library only."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 10000
FIELDS = {'word': ('word','term','单词','词汇'), 'meaning': ('meaning','definition','释义','中文','词义'),
          'example': ('example','sentence','例句'), 'translation': ('translation','sentence_translation','翻译','例句翻译','句子翻译'),
          'scene': ('scene','topic','场景','主题')}

def clean(value, limit=1200):
    if value is None: return ''
    if not isinstance(value, str): raise ValueError('fields must contain text')
    value = unicodedata.normalize('NFKC', value).replace('\r\n','\n').replace('\r','\n').strip()
    if len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value): raise ValueError('text is too long or contains control characters')
    return value

def identity(kind, value):
    fields = ('word','meaning','example','translation','scene') if kind=='word' else ('text','translation','scene')
    values=[clean(value.get(k,'')) for k in fields]
    values[0]=values[0].lower()
    return hashlib.sha256(json.dumps([kind,*values],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:24]

def normalize_item(raw, kind='word', source='import'):
    if isinstance(raw,str): raw={'word' if kind=='word' else 'text':raw}
    if not isinstance(raw,dict): raise ValueError('each item must be an object or text')
    fields=('word','meaning','example','translation','scene') if kind=='word' else ('text','translation','scene')
    item={k:clean(raw.get(k,''),200 if k in ('word','scene') else 1200) for k in fields}
    primary='word' if kind=='word' else 'text'
    if not item[primary]: raise ValueError('word or sentence is empty')
    item['source']='starter' if source=='starter' else 'import'
    item['id']=identity(kind,item)
    return item

def dedup(values):
    result=[];seen=set()
    for item in values:
        if item['id'] not in seen: seen.add(item['id']);result.append(item)
    return result

def normalize_library(raw, source='import'):
    if not isinstance(raw,dict): raise ValueError('library must be an object')
    if raw.get('module_id','english-slices')!='english-slices' or raw.get('schema_version',1)!=1: raise ValueError('unsupported library')
    words=raw.get('words',[]);phrases=raw.get('phrases',[])
    if not isinstance(words,list) or not isinstance(phrases,list) or len(words)+len(phrases)>MAX_ITEMS: raise ValueError('too many entries')
    words=dedup([normalize_item(x,'word',source if source=='starter' else ('starter' if isinstance(x,dict) and x.get('source')=='starter' else 'import')) for x in words])
    phrases=dedup([normalize_item(x,'phrase',source if source=='starter' else ('starter' if isinstance(x,dict) and x.get('source')=='starter' else 'import')) for x in phrases])
    known={x['id'] for x in words+phrases};progress=raw.get('progress',{})
    seen=progress.get('seen',[]) if isinstance(progress,dict) else []
    if not isinstance(seen,list) or any(not isinstance(x,str) for x in seen): raise ValueError('invalid progress')
    return {'schema_version':1,'module_id':'english-slices','words':words,'phrases':phrases,'progress':{'seen':sorted(set(seen)&known)}}

def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES: raise ValueError('missing, symbolic or oversized file')
    return json.loads(path.read_text(encoding='utf-8'),parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')))

def load_starter(): return normalize_library(read_json(ROOT/'starter.json'),'starter')

def parse_import(content, fmt='auto'):
    if not isinstance(content,str) or len(content.encode('utf-8'))>MAX_BYTES: raise ValueError('import exceeds 2 MiB')
    content=content.lstrip('\ufeff').strip()
    if not content: raise ValueError('import is empty')
    if fmt not in ('auto','json','csv','tsv','txt'): raise ValueError('unsupported import format')
    if fmt=='json' or (fmt=='auto' and content[:1] in '[{'):
        raw=json.loads(content,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')))
        if isinstance(raw,list):raw={'words':raw}
        lib=normalize_library(raw)
    else:
        delimiter='\t' if fmt=='tsv' or (fmt=='auto' and '\t' in content.splitlines()[0]) else ','
        is_table=fmt in ('csv','tsv') or (fmt=='auto' and delimiter in content.splitlines()[0])
        if is_table:
            try:rows=list(csv.reader(io.StringIO(content),delimiter=delimiter,strict=True))
            except csv.Error:raise ValueError('invalid CSV quoting') from None
            if len(rows)>MAX_ITEMS+1: raise ValueError('too many rows')
            if not rows:raise ValueError('import is empty')
            heads=[x.strip().casefold() for x in rows[0]];mapping={}
            for key,aliases in FIELDS.items():
                index=next((i for i,h in enumerate(heads) if h in aliases),None)
                if index is not None:mapping[key]=index
            if 'word' in mapping: rows=rows[1:]
            else:mapping={k:i for i,k in enumerate(('word','meaning','example','translation','scene'))}
            words=[]
            for row in rows:
                if not any(x.strip() for x in row):continue
                words.append({k:row[i] if i<len(row) else '' for k,i in mapping.items()})
            lib=normalize_library({'words':words})
        else:
            lines=[x.strip() for x in content.splitlines() if x.strip()]
            if len(lines)>MAX_ITEMS:raise ValueError('too many rows')
            lib=normalize_library({'words':lines})
    if not lib['words'] and not lib['phrases']: raise ValueError('import contains no entries')
    return lib

def merge_library(existing, incoming):
    result={'words':existing['words']+incoming['words'],'phrases':existing['phrases']+incoming['phrases'],'progress':{'seen':existing['progress']['seen']+incoming['progress']['seen']}}
    if len(result['words'])+len(result['phrases'])>MAX_ITEMS*2:raise ValueError('too many entries')
    result['words']=dedup(result['words']);result['phrases']=dedup(result['phrases'])
    return normalize_library(result)

def atomic_save(path, library):
    raw=json.dumps(normalize_library(library),ensure_ascii=False,indent=2).encode()
    if len(raw)>MAX_BYTES:raise ValueError('saved library exceeds 2 MiB')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('data location cannot be symbolic')
    fd,tmp=tempfile.mkstemp(prefix='.english-',dir=path.parent)
    try:
        if hasattr(os,'fchmod'):os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
