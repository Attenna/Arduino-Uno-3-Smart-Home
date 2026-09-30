"""SQLite persistence for the actual Module A / B serial protocol.

All persisted times use UTC. Hardware data never comes from UI button clicks.
Migration preserves legacy history and excludes simulated samples from new charts.
"""
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
SENSORS = ('temperature', 'humidity', 'light_raw', 'smoke', 'rain', 'distance',
           'touch', 'motion', 'soil_moisture', 'soil_dry')
OUTPUTS = ('door_status', 'window_status', 'fan_speed', 'fan_level',
           'light_status', 'light_brightness', 'light_level', 'buzzer_status')


def utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')


def normalize_uid(value):
    uid = re.sub(r'[\s:-]', '', str(value or '')).upper()
    if len(uid) not in (8, 14, 20) or not re.fullmatch(r'[0-9A-F]+', uid):
        raise ValueError('RFID UID 必须为 4、7 或 10 字节十六进制卡号')
    return ' '.join(uid[i:i+2] for i in range(0, len(uid), 2))


def number(value, low, high, integer=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('传感器数值类型错误')
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError('传感器数值超出范围')
    if integer and int(value) != value:
        raise ValueError('需要整数')
    return int(value) if integer else float(value)


def boolean(value):
    if type(value) is not bool:
        raise ValueError('需要布尔状态')
    return int(value)


class SmartHomeDB:
    def __init__(self, db_path=None):
        configured = db_path or os.environ.get('SMART_HOME_DB')
        if configured:
            selected = Path(configured)
        else:
            # The old application used a path relative to its launch directory.
            # Import an existing database from there rather than silently start empty.
            local = BASE / 'smart_home.db'
            previous = Path.cwd() / 'smart_home.db'
            selected = local if local.exists() or not previous.exists() else previous
        self.db_path = str(selected.resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()

    def get_connection(self):
        c = sqlite3.connect(self.db_path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    @contextmanager
    def connection(self):
        c = self.get_connection()
        try:
            with c:
                yield c
        finally:
            c.close()

    def init_database(self):
        # Back up any pre-migration database using SQLite's consistent backup API.
        with self.connection() as c:
            c.execute('PRAGMA journal_mode=WAL')
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version < 2 and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_status'").fetchone():
                backup_path = self.db_path + '.before-hardware-v2.bak'
                if not Path(backup_path).exists():
                    with sqlite3.connect(backup_path) as backup:
                        c.backup(backup)
            c.execute('BEGIN IMMEDIATE')
            c.execute('''CREATE TABLE IF NOT EXISTS system_status (
                id INTEGER PRIMARY KEY CHECK(id=1), temperature REAL, humidity REAL,
                fan_speed INTEGER, ac_status TEXT, ac_temperature REAL,
                door_status TEXT, window_status TEXT, light_status TEXT,
                light_brightness INTEGER, last_updated TEXT)''')
            extra = {k: 'INTEGER' for k in ('light_raw','smoke','rain','distance','touch','motion','soil_moisture','soil_dry','fan_level','light_level','device_uptime_ms')}
            extra.update({k: 'TEXT' for k in ('buzzer_status','sensor_last_seen','output_last_seen')})
            columns = {r['name'] for r in c.execute('PRAGMA table_info(system_status)')}
            for key, kind in extra.items():
                if key not in columns:
                    c.execute(f'ALTER TABLE system_status ADD COLUMN {key} {kind}')
            c.execute('INSERT OR IGNORE INTO system_status(id) VALUES(1)')
            if version < 2:
                keys = list(SENSORS) + list(OUTPUTS) + ['ac_status','ac_temperature','last_updated','sensor_last_seen','output_last_seen']
                c.execute('UPDATE system_status SET ' + ','.join(k+'=NULL' for k in keys))
            old = list(c.execute('PRAGMA table_info(temperature_history)'))
            if old and 'source' not in {r['name'] for r in old}:
                c.execute('ALTER TABLE temperature_history RENAME TO temperature_history_legacy')
            c.execute('''CREATE TABLE IF NOT EXISTS temperature_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                temperature REAL, humidity REAL, source TEXT NOT NULL DEFAULT 'hardware')''')
            if old and 'source' not in {r['name'] for r in old}:
                c.execute("INSERT INTO temperature_history SELECT id,timestamp,temperature,humidity,'legacy' FROM temperature_history_legacy")
                c.execute('DROP TABLE temperature_history_legacy')
            definitions = {
                'door_window_history': 'id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, device_type TEXT NOT NULL, device_name TEXT NOT NULL, status TEXT NOT NULL',
                'light_history': 'id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, light_name TEXT NOT NULL, status TEXT NOT NULL, brightness INTEGER',
                'access_logs': 'id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, person_name TEXT NOT NULL, access_type TEXT NOT NULL, status TEXT NOT NULL',
                'authorized_persons': 'id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, rfid_tag TEXT, face_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP',
                'face_events': "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, face_id TEXT, person_name TEXT, confidence REAL, image_path TEXT, device_source TEXT, status TEXT DEFAULT 'pending', verified INTEGER DEFAULT 0",
                'sensor_history': 'id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT NOT NULL, device_uptime_ms INTEGER, temperature REAL, humidity REAL, light_raw INTEGER, smoke INTEGER, rain INTEGER, distance INTEGER, touch INTEGER, motion INTEGER, soil_moisture INTEGER, soil_dry INTEGER',
                'hardware_events': 'id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT NOT NULL, module TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL',
                'automation_logs': 'id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, rule_id TEXT NOT NULL, rule_name TEXT NOT NULL, triggered INTEGER NOT NULL, conditions_hold INTEGER NOT NULL, reason TEXT, success INTEGER NOT NULL DEFAULT 0, detail_json TEXT',
            }
            for table, definition in definitions.items():
                c.execute(f'CREATE TABLE IF NOT EXISTS {table} ({definition})')
            additions = {'authorized_persons': {'rfid_uid':'TEXT', 'enabled':'INTEGER NOT NULL DEFAULT 0'},
                         'access_logs': {'credential':'TEXT', 'command_status':'TEXT'}}
            for table, fields in additions.items():
                names = {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
                for key, definition in fields.items():
                    if key not in names:
                        c.execute(f'ALTER TABLE {table} ADD COLUMN {key} {definition}')
            if version < 2:
                # Keep every old person; only unambiguous real UIDs become active.
                groups = {}
                for row in c.execute('SELECT id,rfid_tag FROM authorized_persons'):
                    try:
                        groups.setdefault(normalize_uid(row['rfid_tag']), []).append(row['id'])
                    except ValueError:
                        pass
                for uid, ids in groups.items():
                    if len(ids) == 1:
                        c.execute('UPDATE authorized_persons SET rfid_uid=?,enabled=1 WHERE id=?', (uid,ids[0]))
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS unique_rfid_uid ON authorized_persons(rfid_uid) WHERE rfid_uid IS NOT NULL')
            for table, col in [('sensor_history','received_at'),('hardware_events','received_at'),('temperature_history','timestamp'),('door_window_history','timestamp'),('light_history','timestamp'),('access_logs','timestamp'),('face_events','timestamp'),('automation_logs','timestamp')]:
                c.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}({col})')
            c.execute('PRAGMA user_version=2')

    def _rows(self, sql, args=()):
        with self.connection() as c:
            return [dict(r) for r in c.execute(sql, args)]

    @staticmethod
    def _update(c, values):
        c.execute('UPDATE system_status SET '+','.join(k+'=?' for k in values)+' WHERE id=1', tuple(values.values()))

    def get_current_status(self):
        result = self._rows('SELECT * FROM system_status WHERE id=1')[0]
        now = datetime.now(timezone.utc)
        for module, fields in [('sensor', SENSORS), ('output', OUTPUTS)]:
            seen = result.get(module+'_last_seen')
            online = False
            if seen:
                age = (now-datetime.fromisoformat(seen).replace(tzinfo=timezone.utc)).total_seconds()
                online = 0 <= age < 15
            result[module+'_online'] = online
            if not online:
                for field in fields:
                    result[field] = None
        return result

    def update_status(self, **kwargs):
        # Compatibility API; HTTP control routes must never call this optimistically.
        allowed = set(SENSORS + OUTPUTS) | {'ac_status','ac_temperature'}
        values = {k:v for k,v in kwargs.items() if k in allowed}
        if values:
            values['last_updated'] = utcnow()
            with self.connection() as c:
                self._update(c, values)
        return self.get_current_status()

    def ingest_sensor(self, message):
        if message.get('module') != 'sensor' or message.get('type') != 'data':
            raise ValueError('非 A 板数据')
        data = message['data']
        # V2.1 固件已移除超声波(distance)/土壤(soil_*)；缺失字段写 NULL，
        # 绝不能因单个字段缺失丢掉整帧（否则仪表盘与自动化引擎全部断粮）。
        values = {k: number(data.get(k), *bounds)
                  for k, bounds in {'temperature': (-50, 100), 'humidity': (0, 100)}.items()}
        for name, source, maximum in [('light_raw', 'light', 1023),
                                      ('distance', 'distance', 400),
                                      ('soil_moisture', 'soil_moisture', 1023)]:
            values[name] = number(data[source], 0, maximum, True) if source in data else None
        for name in ('smoke', 'rain', 'touch', 'motion', 'soil_dry'):
            values[name] = boolean(data[name]) if name in data else None
        uptime = number(message['timestamp'],0,4294967295,True)
        seen = utcnow()
        with self.connection() as c:
            sample = {'received_at':seen,'device_uptime_ms':uptime,**values}
            c.execute('INSERT INTO sensor_history('+','.join(sample)+') VALUES('+','.join('?' for _ in sample)+')',tuple(sample.values()))
            c.execute('INSERT INTO temperature_history(timestamp,temperature,humidity) VALUES(?,?,?)',(seen,values['temperature'],values['humidity']))
            self._update(c, {**values,'sensor_last_seen':seen,'device_uptime_ms':uptime,'last_updated':seen})

    def ingest_output(self, message):
        if message.get('module') != 'output' or message.get('type') != 'state':
            raise ValueError('非 B 板状态')
        if message['door'] not in ('open','closed') or message['window'] not in ('open','closed','normal') or message['buzzer'] not in ('on','off'):
            raise ValueError('B 板状态无效')
        fan = number(message['fan'],0,255,True)
        light = number(message['light'],0,255,True)
        if fan is None or light is None:
            raise ValueError('缺少执行器等级')
        seen = utcnow()
        values = dict(door_status=message['door'],window_status=message['window'],fan_level=fan,
                      fan_speed=100 if fan > 0 else 0,light_level=light,light_brightness=round(light*100/255),
                      light_status='on' if light else 'off',buzzer_status=message['buzzer'],output_last_seen=seen,last_updated=seen)
        with self.connection() as c:
            old = c.execute('SELECT * FROM system_status WHERE id=1').fetchone()
            for device, label in [('door','前门'),('window','客厅窗户')]:
                if old[device+'_status'] != values[device+'_status']:
                    c.execute('INSERT INTO door_window_history(timestamp,device_type,device_name,status) VALUES(?,?,?,?)',(seen,device,label,values[device+'_status']))
            if old['light_level'] != light:
                c.execute('INSERT INTO light_history(timestamp,light_name,status,brightness) VALUES(?,?,?,?)',(seen,'客厅主灯',values['light_status'],values['light_brightness']))
            self._update(c, values)

    def add_hardware_event(self, message):
        with self.connection() as c:
            return c.execute('INSERT INTO hardware_events(received_at,module,event_type,payload_json) VALUES(?,?,?,?)',
                (utcnow(),message['module'],message.get('event',message['type']),json.dumps(message,ensure_ascii=False))).lastrowid

    def add_automation_log(self, rule_id, rule_name, triggered, conditions_hold, reason, success, detail=''):
        with self.connection() as c:
            return c.execute(
                'INSERT INTO automation_logs(rule_id,rule_name,triggered,conditions_hold,reason,success,detail_json) '
                'VALUES(?,?,?,?,?,?,?)',
                (rule_id, rule_name, int(triggered), int(conditions_hold), reason,
                 int(success), detail)).lastrowid

    def get_automation_logs(self, limit=50):
        return self._rows('SELECT * FROM automation_logs ORDER BY id DESC LIMIT ?',
                          (max(1, min(int(limit), 500)),))

    def mark_offline(self, module):
        if module not in ('sensor','output'):
            raise ValueError('未知模块')
        with self.connection() as c:
            self._update(c, {module+'_last_seen':None})

    def _history(self, table, hours=24, hardware_only=False):
        since = (datetime.now(timezone.utc)-timedelta(hours=max(1,min(int(hours),720)))).strftime('%Y-%m-%d %H:%M:%S')
        col = 'received_at' if table in ('sensor_history','hardware_events') else 'timestamp'
        where = " AND source='hardware'" if hardware_only else ''
        # Bound responses; newest 5000 samples for high-frequency sensor data.
        return self._rows(f'SELECT * FROM {table} WHERE {col}>?{where} ORDER BY {col} DESC,id DESC LIMIT 5000',(since,))

    def get_temperature_history(self, hours=24):
        since = (datetime.now(timezone.utc)-timedelta(hours=max(1,min(int(hours),720)))).strftime('%Y-%m-%d %H:%M:%S')
        # Bucket the full requested range into <= 1440 intervals, ignoring NULLs.
        bucket_seconds = max(60, int(hours)*3600//1440)
        return self._rows("SELECT MIN(timestamp) timestamp, AVG(temperature) temperature, AVG(humidity) humidity FROM temperature_history WHERE timestamp>? AND source='hardware' GROUP BY CAST(strftime('%s',timestamp) AS INTEGER)/? ORDER BY timestamp DESC",(since,bucket_seconds))

    def get_sensor_history(self, hours=24):
        return self._history('sensor_history',hours)

    def get_hardware_events(self, hours=24):
        return self._history('hardware_events',hours)

    def get_door_window_history(self, hours=24):
        return self._history('door_window_history',hours)

    def get_light_history(self, hours=24):
        return self._history('light_history',hours)

    def add_door_window_event(self, device_type, device_name, status):
        with self.connection() as c:
            c.execute('INSERT INTO door_window_history(timestamp,device_type,device_name,status) VALUES(?,?,?,?)',(utcnow(),device_type,device_name,status))

    def add_light_event(self, light_name, status, brightness):
        with self.connection() as c:
            c.execute('INSERT INTO light_history(timestamp,light_name,status,brightness) VALUES(?,?,?,?)',(utcnow(),light_name,status,brightness))

    def get_access_logs(self, limit=50):
        return self._rows('SELECT * FROM access_logs ORDER BY id DESC LIMIT ?',(max(1,min(int(limit),500)),))

    def add_access_log(self, person_name, access_type, status, credential=None, command_status=None):
        with self.connection() as c:
            return c.execute('INSERT INTO access_logs(timestamp,person_name,access_type,status,credential,command_status) VALUES(?,?,?,?,?,?)',
                             (utcnow(),person_name,access_type,status,credential,command_status)).lastrowid

    def get_authorized_persons(self):
        return self._rows('SELECT * FROM authorized_persons WHERE enabled=1 ORDER BY id')

    def find_authorized(self, credential, kind):
        if not credential or kind not in ('rfid','face'):
            return None
        if kind == 'rfid':
            try:
                credential = normalize_uid(credential)
            except ValueError:
                return None
        col = 'rfid_uid' if kind == 'rfid' else 'face_id'
        rows = self._rows(f'SELECT * FROM authorized_persons WHERE enabled=1 AND {col}=?',(credential,))
        return rows[0] if len(rows) == 1 else None

    def add_authorized_person(self, name, rfid_tag=None, face_id=None):
        name, face_id = name.strip(), (face_id or '').strip() or None
        uid = normalize_uid(rfid_tag) if rfid_tag else None
        if not name or not (uid or face_id):
            raise ValueError('姓名及至少一种有效身份标识不能为空')
        try:
            with self.connection() as c:
                c.execute('BEGIN IMMEDIATE')
                if face_id and c.execute('SELECT 1 FROM authorized_persons WHERE face_id=? AND enabled=1',(face_id,)).fetchone():
                    return False
                # Explicit enrollment can re-activate a preserved legacy person.
                old = c.execute('SELECT id,enabled FROM authorized_persons WHERE name=?',(name,)).fetchone()
                if old and not old['enabled']:
                    c.execute('UPDATE authorized_persons SET rfid_tag=?,rfid_uid=?,face_id=?,enabled=1 WHERE id=?',(uid,uid,face_id,old['id']))
                else:
                    c.execute('INSERT INTO authorized_persons(name,rfid_tag,rfid_uid,face_id,enabled) VALUES(?,?,?,?,1)',(name,uid,uid,face_id))
            return True
        except sqlite3.IntegrityError:
            return False

    def get_statistics(self):
        temp = self._rows("SELECT AVG(temperature) avg,MAX(temperature) max,MIN(temperature) min,AVG(humidity) avg_humidity FROM temperature_history WHERE source='hardware' AND timestamp>datetime('now','-24 hours')")[0]
        temp = {k:round(v,2) if v is not None else None for k,v in temp.items()}
        access = self._rows("SELECT COUNT(*) total,COALESCE(SUM(status='granted'),0) granted,COALESCE(SUM(status='denied'),0) denied FROM access_logs WHERE timestamp>datetime('now','-24 hours')")[0]
        light = self._rows("SELECT COUNT(*) total_changes,COALESCE(SUM(status='on'),0) on_count FROM light_history WHERE timestamp>datetime('now','-24 hours')")[0]
        return {'temperature_24h':temp,'access_24h':access,'light_24h':light}

    def add_face_event(self, face_id, person_name=None, confidence=None, image_path=None, device_source='orange_pi'):
        with self.connection() as c:
            return c.execute('INSERT INTO face_events(timestamp,face_id,person_name,confidence,image_path,device_source) VALUES(?,?,?,?,?,?)',
                (utcnow(),face_id,person_name,confidence,image_path,device_source)).lastrowid

    def get_face_events(self, limit=20):
        return self._rows('SELECT * FROM face_events ORDER BY id DESC LIMIT ?',(max(1,min(int(limit),500)),))

    def get_latest_face_event(self):
        rows = self.get_face_events(1)
        return rows[0] if rows else None

    def update_face_event_status(self, event_id, status, verified=False):
        with self.connection() as c:
            return c.execute('UPDATE face_events SET status=?,verified=? WHERE id=?',(status,int(verified),event_id)).rowcount > 0

