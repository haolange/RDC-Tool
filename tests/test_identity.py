import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from rdc_tool.environment import validate_environment

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[1]


def test_current_environment_and_empty_old_variable():
    validate_environment({'RDC_TOOL_INTERMEDIATE_ROOT': 'chosen'})
    with pytest.raises(ValueError, match='RDC_TOOL_INTERMEDIATE_ROOT'):
        validate_environment({'RDX_INTERMEDIATE_ROOT': ''})


def test_retired_environment_fails_before_version_or_runtime(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('RDX_')}
    env['RDX_INTERMEDIATE_ROOT'] = str(tmp_path / 'must-not-create')
    result = subprocess.run([sys.executable, str(ROOT / 'cli/run_cli.py'), '--version'], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload['ok'] is False
    assert payload['error']['code'] == 'setup_failure'
    assert 'RDC_TOOL_INTERMEDIATE_ROOT' in payload['error']['message']
    assert not (tmp_path / 'must-not-create').exists()
