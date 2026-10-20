"""Run checks with external providers mocked and PostgreSQL schemas isolated."""
import os
import sys
import unittest
import json
from collections import defaultdict
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.routing import compile_path
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if __name__ == '__main__':
    url = os.getenv('TEST_DATABASE_URL') or dotenv_values(ROOT / '.env').get('DATABASE_MIGRATION_URL') or dotenv_values(ROOT / '.env').get('DATABASE_URL')
    if not url:
        raise SystemExit('Cần TEST_DATABASE_URL hoặc DATABASE_URL trong .env để kiểm thử PostgreSQL.')
    os.environ['TEST_DATABASE_URL'] = url
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
    from server.main import app
    routes = [(method.upper(), path, compile_path(path)[0])
              for path, operations in app.openapi()['paths'].items() if path.startswith('/api/')
              for method in operations if method.lower() in {'get','post','put','patch','delete'}]
    coverage = defaultdict(set)
    original_request = TestClient.request
    def observed_request(client, method, url, *args, **kwargs):
        response = original_request(client, method, url, *args, **kwargs)
        # Record only declared route templates and status codes. Never store
        # bodies, cookies, query strings, account IDs or recovery/invite tokens.
        actual_paths = client.app.openapi().get('paths', {}) if hasattr(client.app, 'openapi') else {}
        for verb, path, regex in routes:
            if method.upper() == verb and regex.fullmatch(response.request.url.path) and method.lower() in actual_paths.get(path, {}):
                coverage[(verb, path)].add(response.status_code)
                break
        return response
    with patch.object(TestClient, 'request', observed_request):
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'testsRun': result.testsRun, 'passed': result.wasSuccessful(), 'routes': []}
    for method, path, _ in routes:
        report['routes'].append({'method': method, 'path': path,
            'testedStatuses': sorted(coverage.get((method, path), set()))})
    (ROOT/'artifacts/acceptance-route-coverage.json').write_text(json.dumps(report, indent=2))
    raise SystemExit(not result.wasSuccessful())
