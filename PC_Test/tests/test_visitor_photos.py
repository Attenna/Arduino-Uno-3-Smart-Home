import os
import tempfile
import unittest
from pathlib import Path
from web.database import SmartHomeDB
from web.visitor_photos import VisitorPhotos


class VisitorPhotosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = SmartHomeDB(Path(self.temp.name) / 'test.db')
        self.now = 1800000000
        self.store = VisitorPhotos(self.db, clock=lambda: self.now)
        self.jpeg = b'\xff\xd8test\xff\xd9'
        self.face = {'face_id': '', 'bbox': dict(x1=10, y1=10, x2=100, y2=100)}

    def test_same_track_throttles_but_new_person_saves(self):
        self.assertEqual(len(self.store.capture(self.jpeg, [self.face])), 1)
        self.now += 2
        self.assertEqual(self.store.capture(self.jpeg, [self.face]), {})
        other = {'face_id': '', 'bbox': dict(x1=200, y1=10, x2=290, y2=100)}
        self.assertEqual(list(self.store.capture(self.jpeg, [self.face, other])), [1])
        self.now += 31
        self.assertEqual(len(self.store.capture(self.jpeg, [self.face, other])), 2)

    def test_long_visit_retains_one_photo_and_updates_last_seen(self):
        name = self.store.capture(self.jpeg, [self.face])[0]
        for _ in range(12):
            self.now += 3
            self.assertEqual(self.store.capture(self.jpeg, [self.face]), {})
        self.assertEqual((self.store.directory / name).stat().st_mtime, self.now)
        self.assertEqual(len(list(self.store.directory.iterdir())), 1)

    def test_departure_then_reentry_saves_again(self):
        self.store.capture(self.jpeg, [self.face])
        self.now += 7
        self.assertEqual(len(self.store.capture(self.jpeg, [self.face])), 1)

    def test_enabled_person_not_saved_disabled_person_saved(self):
        person = self.db.create_person('resident')
        self.db.set_person_face(person['id'], 'resident')
        self.db.set_person_enabled(person['id'], True)
        face = dict(self.face, face_id='resident')
        self.assertFalse(self.store.capture(self.jpeg, [face]))
        self.db.set_person_enabled(person['id'], False)
        self.assertEqual(len(self.store.capture(self.jpeg, [face])), 1)

    def test_retention_clears_reference_preserves_registration(self):
        name = self.store.capture(self.jpeg, [self.face])[0]
        self.db.add_face_event(face_id='', image_path=name, status='denied')
        path = self.store.directory / name
        os.utime(path, (self.now - 31*86400, self.now - 31*86400))
        protected = self.store.directory / 'registration.jpg'
        protected.write_bytes(self.jpeg)
        self.now += 3601
        self.store.cleanup()
        self.assertFalse(path.exists())
        self.assertTrue(protected.exists())
        self.assertEqual(self.db.get_latest_face_event()['image_path'], '')

    def test_watcher_saves_same_frame_and_api_requires_login(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from flask import Flask
        from werkzeug.security import generate_password_hash
        from web.access_guard import AccessGuard
        from web.face_watcher import FaceWatcher
        from web.api import face as face_api
        from web.auth import install_auth
        guard = AccessGuard(self.db)
        engine = SimpleNamespace(identity_count=lambda: 1, recognize_jpeg=lambda *a, **kw: {
            'detected': True, 'faces': [self.face], 'face_id': ''})
        watcher = FaceWatcher(engine, guard, {'face': {'watcher': {'motion_gate': False, 'min_face_px': 0}}})
        watcher.grab_frame = lambda: self.jpeg
        watcher.snapshot_url = 'http://fixture/snapshot'
        watcher.inspect_once()
        event = self.db.get_latest_face_event()
        self.assertEqual(event['status'], 'denied')
        self.assertEqual((self.store.directory / event['image_path']).read_bytes(), self.jpeg)
        app = Flask(__name__)
        with patch.dict(os.environ, {'SMART_HOME_ADMIN_USER': 'fixture', 'SMART_HOME_ADMIN_PASSWORD_HASH': generate_password_hash('fixture'),
                                    'SMART_HOME_SESSION_SECRET': 's'*48, 'SMART_HOME_SERVICE_TOKEN': 't'*48}):
            install_auth(app)
        app.register_blueprint(face_api.bp)
        client = app.test_client()
        with patch.object(face_api, 'db', self.db):
            self.assertEqual(client.get('/api/face/visitors').status_code, 401)
            url = '/api/face/visitors/images/' + event['image_path']
            self.assertEqual(client.get(url).status_code, 401)
            with client.session_transaction() as session:
                session['user'] = 'fixture'
            listing = client.get('/api/face/visitors').get_json()
            self.assertEqual(len(listing), 1)
            response = client.get(listing[0]['image_url'])
            self.assertEqual(response.data, self.jpeg)
            response.close()
            self.assertEqual(client.get('/api/face/visitors/images/registration.jpg').status_code, 404)

    def test_photo_write_failure_does_not_stop_denial(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from web.access_guard import AccessGuard
        from web.face_watcher import FaceWatcher
        engine = SimpleNamespace(identity_count=lambda: 1, recognize_jpeg=lambda *a, **kw: {
            'detected': True, 'faces': [self.face], 'face_id': ''})
        watcher = FaceWatcher(engine, AccessGuard(self.db), {'face': {'watcher': {'min_face_px': 0}}})
        watcher.snapshot_url = 'http://fixture/snapshot'
        watcher.grab_frame = lambda: self.jpeg
        watcher._visitor_photos = self.store
        with patch.object(self.store, 'capture', side_effect=OSError('fixture disk full')):
            watcher.inspect_once()
        self.assertEqual(self.db.get_latest_face_event()['status'], 'denied')
        self.assertEqual(self.db.get_latest_face_event()['image_path'], '')

    def test_authorized_primary_does_not_hide_unknown_secondary(self):
        from types import SimpleNamespace
        from web.access_guard import AccessGuard
        from web.face_watcher import FaceWatcher
        person = self.db.create_person('resident')
        self.db.set_person_face(person['id'], 'resident')
        self.db.set_person_enabled(person['id'], True)
        known = dict(self.face, face_id='resident')
        unknown = dict(self.face, bbox=dict(x1=200, y1=10, x2=290, y2=100))
        engine = SimpleNamespace(identity_count=lambda: 1, recognize_jpeg=lambda *a, **kw: {
            'detected': True, 'faces': [known, unknown], 'face_id': 'resident'})
        watcher = FaceWatcher(engine, AccessGuard(self.db), {'face': {'watcher': {'min_face_px': 0}}})
        watcher.snapshot_url = 'http://fixture/snapshot'
        watcher.grab_frame = lambda: self.jpeg
        watcher.inspect_once()
        events = self.db.get_face_events(limit=10)
        denied = [row for row in events if row['status'] == 'denied']
        self.assertEqual(len(denied), 1)
        self.assertTrue(denied[0]['image_path'].startswith('visitor_'))
        self.assertEqual(self.db.get_latest_face_event()['status'], 'granted')
