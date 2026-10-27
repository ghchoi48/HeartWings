"""배포 도구 없이 빌드 순서, 오류 전파 및 메타데이터 전달을 검증한다."""
import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    'build_desktop', Path(__file__).resolve().parents[1] / 'scripts/build_desktop.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(build.sys, 'platform', 'win32')
    monkeypatch.setattr(build.platform, 'machine', lambda: 'AMD64')
    monkeypatch.setattr(build.struct, 'calcsize', lambda _: 8)
    runner = Mock()
    monkeypatch.setattr(build.subprocess, 'run', runner)
    return runner


@pytest.fixture
def compiler_env(monkeypatch):
    for key in ('ISCC_PATH', 'ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(build.shutil, 'which', lambda _: None)


def test_explicit_compiler_wins(tmp_path, monkeypatch, compiler_env):
    compiler = tmp_path / '한글 경로' / 'ISCC.exe'
    compiler.parent.mkdir()
    compiler.touch()
    monkeypatch.setenv('ISCC_PATH', str(compiler))
    monkeypatch.setattr(build.shutil, 'which', lambda _: 'different.exe')
    assert build.find_iscc() == compiler


def test_invalid_explicit_compiler_is_error(monkeypatch, compiler_env):
    monkeypatch.setenv('ISCC_PATH', '/missing/ISCC.exe')
    monkeypatch.setattr(build.shutil, 'which', lambda _: 'different.exe')
    with pytest.raises(RuntimeError, match='ISCC_PATH'):
        build.find_iscc()


def test_path_compiler(monkeypatch, compiler_env):
    monkeypatch.setattr(build.shutil, 'which', lambda _: 'C:/Tools/ISCC.exe')
    assert build.find_iscc() == Path('C:/Tools/ISCC.exe')


@pytest.mark.parametrize('variable,relative', [
    ('ProgramFiles(x86)', 'Inno Setup 6'), ('ProgramFiles', 'Inno Setup 6'),
    ('LOCALAPPDATA', 'Programs/Inno Setup 6'),
])
def test_default_compiler_locations(tmp_path, monkeypatch, compiler_env, variable, relative):
    compiler = tmp_path / relative / 'ISCC.exe'
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    monkeypatch.setenv(variable, str(tmp_path))
    assert build.find_iscc() == compiler


def test_missing_compiler_stops_before_pyinstaller(windows, compiler_env):
    with pytest.raises(RuntimeError, match='Inno Setup'):
        build.main()
    windows.assert_not_called()


@pytest.mark.parametrize('machine,bits', [('ARM64', 8), ('AMD64', 4), ('x86', 4)])
def test_unsupported_python_stops_before_build(windows, monkeypatch, machine, bits):
    monkeypatch.setattr(build.platform, 'machine', lambda: machine)
    monkeypatch.setattr(build.struct, 'calcsize', lambda _: bits)
    with pytest.raises(RuntimeError, match='x64'):
        build.main()
    windows.assert_not_called()


def test_windows_build_passes_metadata_as_separate_arguments(windows, monkeypatch, tmp_path):
    root = tmp_path / '한글 프로젝트'
    info = root / 'maeumnarae/core/program_info.py'
    info.parent.mkdir(parents=True)
    info.write_text("raise RuntimeError('must not import')\nPROGRAM_NAME = '마음 나래'\nPROGRAM_VERSION = '2.3.4'\n", encoding='utf-8')
    monkeypatch.setattr(build, 'ROOT', root)
    monkeypatch.setattr(build, 'find_iscc', lambda: Path('C:/Inno Setup 6/ISCC.exe'))
    build.main()
    assert windows.call_count == 2
    first, second = windows.call_args_list
    assert first.args[0][1:3] == ['-m', 'PyInstaller']
    assert second.args[0] == ['C:/Inno Setup 6/ISCC.exe', '/DAppName=마음 나래',
                             '/DAppVersion=2.3.4', f'/DSourceRoot={root}',
                             str(root / 'packaging/maeumnarae.iss')]
    assert first.kwargs['check'] and second.kwargs['check']


@pytest.mark.parametrize('failed_stage', [0, 1])
def test_build_failure_propagates(windows, monkeypatch, failed_stage):
    monkeypatch.setattr(build, 'find_iscc', lambda: Path('ISCC.exe'))
    failure = subprocess.CalledProcessError(7, 'build')
    windows.side_effect = [failure] if failed_stage == 0 else [None, failure]
    with pytest.raises(subprocess.CalledProcessError) as exc:
        build.main()
    assert exc.value.returncode == 7
    assert windows.call_count == failed_stage + 1


@pytest.mark.parametrize('target,count', [('darwin', 2), ('linux', 1)])
def test_non_windows_build_does_not_require_inno(monkeypatch, target, count):
    monkeypatch.setattr(build.sys, 'platform', target)
    runner = Mock()
    monkeypatch.setattr(build.subprocess, 'run', runner)
    compiler = Mock(side_effect=AssertionError('must not look for Inno Setup'))
    monkeypatch.setattr(build, 'find_iscc', compiler)
    build.main()
    assert runner.call_count == count
    compiler.assert_not_called()
    if target == 'darwin':
        assert runner.call_args.args[0][0] == 'ditto'


def test_bad_version_stops_before_build(windows, monkeypatch):
    monkeypatch.setattr(build, 'find_iscc', lambda: Path('ISCC.exe'))
    monkeypatch.setattr(build.ast, 'parse', lambda _: ast_tree())
    with pytest.raises(RuntimeError, match='버전'):
        build.main()
    windows.assert_not_called()


def ast_tree():
    import ast
    return ast.Module(body=[ast.Assign(targets=[ast.Name(id='PROGRAM_NAME')], value=ast.Constant('마음나래')),
                            ast.Assign(targets=[ast.Name(id='PROGRAM_VERSION')], value=ast.Constant('bad-version'))])
