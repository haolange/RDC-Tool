"""Convert inspect-rdc DXBC artifacts with installed vkd3d/SPIRV tools.

This is static shader translation and validation, not frame replay or a guarantee
that generated shader code is semantically equivalent on a particular device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inspection', type=Path)
    args = parser.parse_args()
    tools = {name: shutil.which(name) for name in ('vkd3d-compiler','spirv-val','spirv-dis','spirv-cross')}
    if not all(tools.values()): parser.error('Required tools missing from PATH: '+', '.join(k for k,v in tools.items() if not v))
    source = args.inspection.resolve(); output = source/'shader-analysis'
    output.mkdir(exist_ok=True)
    if any(output.iterdir()): parser.error('shader-analysis must be empty; results are never overwritten')
    rows = []
    for shader in json.loads((source/'shaders.json').read_text()):
        path = source/'shaders'/shader['file']
        if path.resolve().parent != (source/'shaders').resolve(): raise ValueError('Shader path escapes inspection')
        if hashlib.sha256(path.read_bytes()).hexdigest() != shader['sha256']: raise ValueError('Shader hash mismatch')
        row = {'input':shader['file'], 'sha256':shader['sha256'], 'replay_verified':False}
        spv = output/(path.stem+'.spv')
        for label, command in [
            ('compile',[tools['vkd3d-compiler'],'-x','dxbc-tpf','-b','spirv-binary',str(path),'-o',str(spv)]),
            ('validate',[tools['spirv-val'],str(spv)]),
            ('disassemble',[tools['spirv-dis'],str(spv),'-o',str(output/(path.stem+'.spvasm'))]),
            ('glsl',[tools['spirv-cross'],str(spv),'--version','450','--output',str(output/(path.stem+'.glsl'))])]:
            result = subprocess.run(command,capture_output=True,text=True,timeout=30)
            row[label] = {'returncode':result.returncode,'stderr':result.stderr[:4000]}
            if result.returncode: break
        rows.append(row)
        (output/'results.json').write_text(json.dumps(rows,indent=2))
    summary = {'scope':'static_shader_translation','replay_verified':False,'total':len(rows),
        **{key:sum(row.get(key,{}).get('returncode') == 0 for row in rows) for key in ('compile','validate','disassemble','glsl')}}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))
    return 0 if summary['glsl'] == summary['total'] else 1


if __name__ == '__main__': raise SystemExit(main())
