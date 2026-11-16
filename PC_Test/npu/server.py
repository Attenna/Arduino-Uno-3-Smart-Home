"""Private authenticated NPU side service for the existing web container."""
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import numpy as np
from ascend_runner import AscendRunner


def main():
    token = os.environ['SMART_HOME_NPU_TOKEN']
    if len(token) < 32:
        raise ValueError('NPU authentication token must have at least 32 characters')
    path = Path(os.environ['SMART_HOME_NPU_MODEL'])
    runner = AscendRunner(path)
    model_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def authorized(self):
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def reply(self, status, data, kind='application/json'):
            body = json.dumps(data).encode() if kind == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.authorized():
                return self.reply(401, {'error': 'Authentication required'})
            if self.path != '/health':
                return self.reply(404, {'error': 'Unknown endpoint'})
            return self.reply(200, {'provider': 'Ascend310B4', 'input_shape': runner.input_shape,
                                    'output_shape': runner.output_shape, 'om_sha256': model_hash})

        def do_POST(self):
            if not self.authorized():
                return self.reply(401, {'error': 'Authentication required'})
            if self.path != '/infer':
                return self.reply(404, {'error': 'Unknown endpoint'})
            try:
                expected = int(np.prod(runner.input_shape)) * 4
                if int(self.headers.get('Content-Length', 0)) != expected:
                    return self.reply(400, {'error': 'Unexpected input byte size'})
                self.connection.settimeout(10)
                body = self.rfile.read(expected)
                if len(body) != expected:
                    return self.reply(400, {'error': 'Incomplete input'})
                tensor = np.frombuffer(body, dtype=np.float32).reshape(runner.input_shape)
                output = runner.infer(tensor)
                return self.reply(200, output.tobytes(), 'application/octet-stream')
            except Exception as exc:
                return self.reply(503, {'error': str(exc)})

    server = ThreadingHTTPServer((os.environ.get('SMART_HOME_NPU_BIND', '127.0.0.1'), 8093), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        server.server_close()
        runner.close()


if __name__ == '__main__':
    main()
