from pathlib import Path
import sys
import tempfile
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.test_users_authorization import make_v2, login

artifact_dir = ROOT / 'output' / 'playwright'
artifact_dir.mkdir(parents=True, exist_ok=True)
temporary = tempfile.TemporaryDirectory(dir=artifact_dir)
client, manager, data = make_v2(Path(temporary.name))
csrf = login(client, 'ct', data['passwords']['ct'])
headers = {'X-CSRF-Token': csrf}
request_lock = Lock()
plan = client.post('/api/v1/playbook/plans', headers=headers, json={
    'team_id': data['team_id'], 'title': 'Plano fictício de validação',
    'seasonal_objective': 'Teste', 'items': [],
}).json()
for title in ['Sessão A de teste', 'Sessão B de teste']:
    response = client.post('/api/v1/playbook/sessions', headers=headers, json={
        'team_id': data['team_id'], 'plan_id': plan['plan']['id'],
        'title_override': title,
    })
    assert response.status_code == 201, response.text

class Proxy(BaseHTTPRequestHandler):
    def do_GET(self):
        self.forward()
    def do_POST(self):
        self.forward()
    def forward(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        forwarded = {key: value for key, value in self.headers.items()
                     if key.lower() not in {'host', 'cookie', 'origin', 'referer', 'accept-encoding'}}
        with request_lock:
            response = client.request(self.command, self.path, content=body, headers=forwarded)
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            if key.lower() not in {'content-length', 'content-encoding', 'transfer-encoding', 'set-cookie'}:
                self.send_header(key, value)
        self.send_header('Content-Length', str(len(response.content)))
        self.end_headers()
        self.wfile.write(response.content)
    def log_message(self, *args):
        pass

print('Synthetic fixture ready at http://127.0.0.1:8879', flush=True)
ThreadingHTTPServer(('127.0.0.1', 8879), Proxy).serve_forever()
