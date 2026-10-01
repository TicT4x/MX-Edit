"""Baut einen Block/Parameter-Katalog aus Rigs und Block-Presets."""
import json, glob, os, sys, collections
root = sys.argv[1]
cat = collections.OrderedDict()
TYPES = {0: 'number', 1: 'bool', 3: 'bool3', 4: 'enum', 8: 'text'}

def add(module, name, node, src):
    m = cat.setdefault(module, {'params': {}, 'order': [], 'sources': set()})
    m['sources'].add(src)
    p = m['params'].setdefault(name, {'type': TYPES.get(node.get('type'), node.get('type')),
                                      'min': None, 'max': None, 'values': set(), 'n': 0})
    p['n'] += 1
    if 'value' in node:
        v = node['value']
        p['min'] = v if p['min'] is None else min(p['min'], v)
        p['max'] = v if p['max'] is None else max(p['max'], v)
    if 'string' in node and p['type'] == 'enum':
        p['values'].add(node['string'])
    if 'state' in node:
        p['values'].add(node['state'])

def walk_module(module, node, src):
    for k in node.get('childorder', []):
        m = cat.setdefault(module, {'params': {}, 'order': [], 'sources': set()})
        if k not in m['order']: m['order'].append(k)
    for k, v in node.get('children', {}).items():
        add(module, k, v, src)

chains = collections.Counter()
for f in glob.glob(os.path.join(root, 'Rigs', '*.rig')):
    c = json.loads(json.load(open(f, encoding='utf-8'))['content'])
    patch = c['data']['Patch']
    for mod, node in patch.get('children', {}).items():
        walk_module(mod, node, 'rig')
    ch = patch['children'].get('Chain', {}).get('children', {})
    for k, v in ch.items():
        if k.startswith('ModuleType'): chains[v.get('string')] += 1
for f in glob.glob(os.path.join(root, 'Blocks', '*', '*.block')):
    d = json.load(open(f, encoding='utf-8'))
    c = json.loads(d['content'])
    for mod, node in c['data'].items():
        walk_module(mod, node, 'block')

out = {}
for mod, m in cat.items():
    out[mod] = {'order': m['order'], 'sources': sorted(m['sources']), 'params': {
        k: {kk: (sorted(vv, key=str) if isinstance(vv, set) else vv) for kk, vv in p.items()}
        for k, p in m['params'].items()}}
json.dump({'modules': out, 'chain_usage': chains}, open('catalog.json', 'w'), indent=1, ensure_ascii=False)
print('Module:', len(out), ' Parameter gesamt:', sum(len(m['params']) for m in out.values()))
print('In Ketten verwendete Blocktypen:', len(chains))
print('Nur aus Block-Presets:', sorted(k for k,m in out.items() if m['sources']==['block'])[:40])
