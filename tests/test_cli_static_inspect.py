from __future__ import annotations

import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from rdc_tool import cli


def _install_inspector(monkeypatch, inspect):
    module = ModuleType('rdc_tool.static_inspect')
    module.inspect_capture = inspect
    monkeypatch.setitem(sys.modules, 'rdc_tool.static_inspect', module)
    monkeypatch.setattr(cli.asyncio, 'run', lambda *args: pytest.fail('static inspection started an event loop'))
    monkeypatch.setattr(cli, 'ensure_daemon', lambda *args, **kw: pytest.fail('static inspection started a daemon'))


def test_static_parser_requires_capture_and_output():
    parser = cli._build_parser()
    with pytest.raises(SystemExit) as error:
        parser.parse_args(['inspect-rdc', 'capture.rdc'])
    assert error.value.code == 2
    args = parser.parse_args(['inspect-rdc', 'capture.rdc', '--output-dir', 'output'])
    assert args.capture == Path('capture.rdc')
    assert args.output_dir == Path('output')


def test_static_inspection_routes_without_async_or_daemon(monkeypatch, capsys):
    calls = []
    payload = {'ok': True, 'inspection_mode': 'static', 'replay_performed': False}
    def inspect(capture, output_dir):
        calls.append((capture, output_dir))
        return payload
    _install_inspector(monkeypatch, inspect)
    monkeypatch.setattr(sys, 'argv', ['rdc-tool', 'inspect-rdc', 'capture.rdc', '--output-dir', 'output'])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0
    assert calls == [(Path('capture.rdc'), Path('output'))]
    assert json.loads(capsys.readouterr().out) == payload


def test_static_inspection_exception_is_error_not_replay_success(monkeypatch, capsys):
    def inspect(*args):
        raise ValueError('invalid capture fixture')
    _install_inspector(monkeypatch, inspect)
    monkeypatch.setattr(sys, 'argv', ['rdc-tool', 'inspect-rdc', 'bad.rdc', '--output-dir', 'output'])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] is False
    assert 'invalid capture fixture' in result['error']['message']


def test_static_inspection_explicit_failure_is_nonzero(monkeypatch, capsys):
    _install_inspector(monkeypatch, lambda *args: {'ok': False, 'reason': 'unsupported container'})
    monkeypatch.setattr(sys, 'argv', ['rdc-tool', 'inspect-rdc', 'capture.rdc', '--output-dir', 'output'])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out)['ok'] is False


def test_static_help_does_not_claim_replay(capsys):
    with pytest.raises(SystemExit) as error:
        cli._build_parser().parse_args(['inspect-rdc', '--help'])
    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert 'without replay' in help_text
    assert '--output-dir DIR' in help_text
