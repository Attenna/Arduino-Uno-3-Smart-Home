"""Bounded visit tracks and original-frame evidence for denied face events."""
import os
import re
import threading
import time
import uuid
from pathlib import Path

PHOTO_NAME = re.compile(r'visitor_[0-9a-f]{32}\.jpg\Z')


def overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = lambda r: max(0, r[2] - r[0]) * max(0, r[3] - r[1])
    union = area(a) + area(b) - intersection
    return intersection / union if union else 0


class VisitorPhotos:
    def __init__(self, db, directory=None, clock=time.time):
        self.db = db
        self.directory = Path(directory or Path(db.db_path).parent / 'face' / 'visitors')
        self.clock = clock
        self.tracks = []
        self.lock = threading.Lock()
        self.last_cleanup = 0

    def capture(self, jpeg, faces):
        """One-to-one IoU matching per frame. Absence >6s starts a new visit."""
        now = self.clock()
        paths = {}
        with self.lock:
            self.cleanup(now)
            available = [t for t in self.tracks if now - t['seen'] <= 6]
            current = []
            for index, face in enumerate(faces):
                box = face.get('bbox') or {}
                rect = tuple(box.get(k, 0) for k in ('x1', 'y1', 'x2', 'y2'))
                identity = face.get('face_id') or ''
                candidates = [t for t in available if t['identity'] == identity and overlap(t['box'], rect) >= .3]
                track = max(candidates, key=lambda t: overlap(t['box'], rect), default=None)
                if track is None:
                    track = {'saved': float('-inf'), 'identity': identity}
                else:
                    available.remove(track)
                track.update(box=rect, seen=now)
                current.append(track)
                reason = self.db.diagnose(identity, 'face')[0] if identity else 'unmatched_face'
                if reason == 'matched':
                    continue
                if track.get('photo'):
                    os.utime(self.directory / track['photo'], (now, now))
                    continue
                if not jpeg.startswith(b'\xff\xd8'):
                    raise ValueError('Invalid visitor JPEG')
                self.directory.mkdir(parents=True, exist_ok=True)
                name = 'visitor_' + uuid.uuid4().hex + '.jpg'
                temp = self.directory / (name + '.tmp')
                try:
                    temp.write_bytes(jpeg)
                    os.replace(temp, self.directory / name)
                finally:
                    temp.unlink(missing_ok=True)
                paths[index] = name
                track['photo'] = name
                os.utime(self.directory / name, (now, now))
            self.tracks = current + available
        return paths

    def cleanup(self, now=None):
        now = self.clock() if now is None else now
        if now - self.last_cleanup < 3600:
            return
        if self.directory.exists():
            for path in self.directory.iterdir():
                if PHOTO_NAME.fullmatch(path.name) and path.stat().st_mtime < now - 30 * 86400:
                    # Clear references before deleting. A failed unlink is retried next sweep.
                    with self.db.connection() as c:
                        c.execute('UPDATE face_events SET image_path=? WHERE image_path=?', ('', path.name))
                    path.unlink(missing_ok=True)
        self.last_cleanup = now
