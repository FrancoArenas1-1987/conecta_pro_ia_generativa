"""Exercise every service layout with synthetic pixels; no AI calls or publishing."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from instagram_image_factory import DbService, FONTS, load_db_services, preflight_layout


def check(services, work_dir):
    results = []
    for service in services:
        try:
            result = preflight_layout(service, work_dir)
            results.append({**asdict(service), 'ok': True, 'layout': result['layout']})
        except Exception as exc:
            results.append({**asdict(service), 'ok': False, 'error': str(exc)})
    return {'ok': bool(results) and all(r['ok'] for r in results),
            'checked': len(results), 'failed': sum(not r['ok'] for r in results),
            'fonts': {k: str(getattr(v, 'path', 'default')) for k, v in FONTS.items()},
            'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry-snapshot', type=Path, help='Offline JSON service registry instead of DB')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.registry_snapshot:
        registry = json.loads(args.registry_snapshot.read_text(encoding='utf-8'))
        services = [DbService(code, row['name'], row.get('provider_count', 0))
                    for code, row in registry['services'].items() if row.get('active')]
    else:
        services = load_db_services(min_providers=1)
    with tempfile.TemporaryDirectory(prefix='ig-layout-check-') as directory:
        report = check(services, Path(directory))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'results'}, ensure_ascii=False, indent=2))
    for row in report['results']:
        if not row['ok']:
            print(json.dumps(row, ensure_ascii=False))
    raise SystemExit(0 if report['ok'] else 1)
