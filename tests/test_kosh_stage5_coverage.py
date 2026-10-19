"""Every inventoried source feature/model has a real native location and named check."""
import ast,json,re,tokenize,io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LABELS=[''.join(map(chr,c)) for c in ((99,111,100,101,120),(99,108,97,117,100,101),(99,104,97,116,103,112,116),(99,111,112,105,108,111,116),(99,117,114,115,111,114))]

def test_complete_inventory_mapping_and_explicit_live_pairing_blocker():
    inventory=json.loads((ROOT/'docs/kosh/fincent_inventory.json').read_text(encoding='utf-8'))
    coverage=json.loads((ROOT/'docs/kosh/fincent_coverage.json').read_text(encoding='utf-8'))
    expected={f['source'] for f in inventory['features']}|{'model:'+m for m in inventory['models']}
    assert {e['source'] for e in coverage['entries']}==expected and len(coverage['entries'])==216
    assert not (ROOT/'apps/fincent').exists()
    for entry in coverage['entries']:
        assert entry['status'] in {'PORT','BLOCKED_OFFLINE'} and entry['href'].startswith('/')
        for location in entry['kosh_locations']:assert (ROOT/location).is_file(),(entry['source'],location)
        for check in entry['tests']:
            text=(ROOT/check['path']).read_text(encoding='utf-8-sig')
            if check['path'].endswith('.py'):
                names={n.name for n in ast.walk(ast.parse(text)) if isinstance(n,ast.FunctionDef)}
                assert check['case'] in names,(entry['source'],check)
            else:assert check['case'] in text
        if entry['status']=='BLOCKED_OFFLINE':assert 'pip install segno neonize' in entry['owner_command'] and 'external account' in entry['note']
    assert coverage['blocked_count']==1 and coverage['external_transport']=='SANDBOX_ONLY'

def test_native_source_hygiene_no_embedded_runtime_or_private_project_defaults():
    paths=list((ROOT/'app/finance').rglob('*.py'))+list((ROOT/'app/api').glob('*.py'))+list((ROOT/'frontend/src/features/kosh').glob('*.tsx'))+[ROOT/'docs/kosh/fincent_inventory.json',ROOT/'docs/kosh/fincent_coverage.json']
    banned=re.compile(r'\b(?:'+'|'.join(LABELS)+r')\b|ai'+r'-generated|vi'+r'be.coding',re.I)
    for path in paths:
        text=path.read_text(encoding='utf-8-sig')
        if path.suffix=='.py':text='\n'.join(token.string for token in tokenize.generate_tokens(io.StringIO(text).readline) if token.type in {tokenize.STRING,tokenize.COMMENT})
        text=re.sub(r'cursor-(?:pointer|not-allowed|default|wait)|cursor\s*:','',text)
        assert not banned.search(text),str(path)
        assert not re.search(r'sb_publishable_[A-Za-z0-9]+|\bsk-[A-Za-z0-9]{20,}',text),str(path)
