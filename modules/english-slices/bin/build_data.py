"""Build an offline English-slices preview without importing personal material."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from library import ROOT, load_starter

def json_script(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')

def page(library=None,service_mode=False,parent_origin=''):
    payload={'library':library or load_starter(),'service_mode':service_mode}
    replacements={'__STARTER_JSON__':json_script(payload),'__DESIGN_CSS__':(ROOT/'site/design-system.css').read_text(),
                  '__THEME_JS__':(ROOT/'site/embedded-theme.js').read_text(),'__APP_JS__':(ROOT/'site/app.js').read_text()}
    template=(ROOT/'site.template.html').read_text()
    if parent_origin:
        from urllib.parse import urlsplit
        u=urlsplit(parent_origin)
        if u.scheme not in ('http','https') or u.hostname not in ('127.0.0.1','localhost','::1') or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:raise ValueError('parent origin must be a loopback origin')
        import html
        template=template.replace('data-workhub-theme="codex-light"','data-workhub-theme="codex-light" data-workhub-parent-origin="'+html.escape(parent_origin.rstrip('/'),quote=True)+'"',1)
    for marker in replacements:
        if marker not in template:raise ValueError('missing template marker')
    return re.sub('|'.join(map(re.escape,replacements)),lambda m:replacements[m.group()],template)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--demo',action='store_true',help='use original starter examples, no network or personal data');parser.add_argument('--output',type=Path,default=ROOT/'site/index.html');parser.add_argument('--parent-origin',default='')
    args=parser.parse_args();output=args.output
    if output.is_symlink() or output.parent.is_symlink():parser.error('output cannot be symbolic')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(page(parent_origin=args.parent_origin),encoding='utf-8')
    print(json.dumps({'module':'english-slices','service_mode':False,'words':len(load_starter()['words']),'phrases':len(load_starter()['phrases'])}))
if __name__=='__main__':main()
