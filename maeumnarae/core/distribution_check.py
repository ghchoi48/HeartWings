"""소스 또는 frozen 실행 파일에서 DB 없이 XLSB·동봉 고지를 검증한다."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from maeumnarae.core.program_info import program_license, third_party_notices, third_party_source
from maeumnarae.services.data_management.legacy_import import read_rows, parse_rows, excel_day


def verify(fixture: Path, school_year: int, period_times: dict) -> dict:
    import pyxlsb

    rows = read_rows(fixture.read_bytes())
    batch = parse_rows(rows, school_year, period_times)
    if batch.errors:
        raise ValueError('XLSB 검증 자료의 모델 변환에 실패했습니다.')
    if 'MIT License' not in program_license():
        raise ValueError('MIT 원문을 찾을 수 없습니다.')
    sources = {}
    for entry in third_party_notices()['libraries']:
        if entry['name'] not in ('pyxlsb', 'certifi'):
            continue
        if not entry['text']:
            raise ValueError('라이선스 원문이 비어 있습니다.')
        data = third_party_source(entry['source_file'])
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry['source_sha256']:
            raise ValueError(f"{entry['name']} 원본 소스 해시가 다릅니다.")
        sources[entry['name']] = digest
        if entry.get('modified_source_file'):
            data = third_party_source(entry['modified_source_file'])
            with ZipFile(BytesIO(data)) as archive:
                contents = json.loads(archive.read('CONTENTS.json'))
                if contents['installed_version'] != pyxlsb.__version__:
                    raise ValueError('실행된 pyxlsb와 동봉 소스 버전이 다릅니다.')
                for name, expected in contents['sha256'].items():
                    if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                        raise ValueError(f'동봉 사용 소스 해시 불일치: {name}')
            sources['used_sources'] = hashlib.sha256(data).hexdigest()
    if not {'pyxlsb', 'certifi', 'used_sources'}.issubset(sources):
        raise ValueError('필수 소스 고지가 누락되었습니다.')
    return {'status': 'passed', 'frozen': bool(getattr(sys, 'frozen', False)),
            'pyxlsb_version': pyxlsb.__version__, 'fingerprint': batch.fingerprint,
            'people': len(batch.people), 'logs': len(batch.logs),
            'row_numbers': {name: [number for number, _ in values] for name, values in rows.items()},
            'dates': {str(v): excel_day(v).isoformat() for v in (59, 60, 61, 42005, 46200.75)},
            'source_sha256': sources}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-distribution', type=Path, required=True, metavar='XLSB')
    parser.add_argument('--verification-report', type=Path, required=True)
    parser.add_argument('--school-year', type=int, default=2026)
    parser.add_argument('--period-times', default='{"1":"09:00"}', help='교시별 시작 시간 JSON')
    args = parser.parse_args()
    try:
        result = verify(args.verify_distribution, args.school_year, json.loads(args.period_times))
        code = 0
    except Exception as error:
        result = {'status': 'failed', 'error': str(error),
                  'frozen': bool(getattr(sys, 'frozen', False))}
        code = 1
    args.verification_report.parent.mkdir(parents=True, exist_ok=True)
    args.verification_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return code
