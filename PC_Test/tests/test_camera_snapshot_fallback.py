"""Exercise the shared capture fallback without loading ML or hardware services."""
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock
import unittest
from flask import Flask

spec = importlib.util.spec_from_file_location('camera_api_test', Path(__file__).parents[1] / 'web/api/camera.py')
camera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera)

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['SMART_HOME_CFG'] = {'camera': {'stream_url': 'http://camera:8080/video_feed'}}
        app.register_blueprint(camera.bp)
        self.client = app.test_client()

    def test_shared_snapshot_is_fresh_jpeg(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'\xff\xd8fixture\xff\xd9'
        with patch.dict(camera.os.environ, {}, clear=True), patch.object(camera.urllib.request, 'urlopen', return_value=response) as fetch:
            result = self.client.get('/api/camera/snapshot')
        fetch.assert_called_once_with('http://camera:8080/snapshot', timeout=5)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.mimetype, 'image/jpeg')
        self.assertEqual(result.headers['Cache-Control'], 'no-store')

    def test_invalid_image_is_unavailable(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'not a jpeg'
        with patch.dict(camera.os.environ, {}, clear=True), patch.object(camera.urllib.request, 'urlopen', return_value=response):
            self.assertEqual(self.client.get('/api/camera/snapshot').status_code, 503)

if __name__ == '__main__':
    unittest.main()
