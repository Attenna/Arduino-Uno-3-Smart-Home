"""SQLite persistence for the actual Module A / B serial protocol.

All persisted times use UTC. Hardware data never comes from UI button clicks.
Migration preserves legacy history and excludes simulated samples from new charts.
"""
import json
import logging
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
SENSORS = ('temperature', 'humidity', 'light_raw', 'smoke', 'rain', 'distance',
           'touch', 'motion', 'soil_moisture', 'soil_dry')
OUTPUTS = ('door_status', 'window_status', 'fan_speed',
           'light_status', 'light_brightness', 'buzzer_status',
           # 灯的「亮法」（白光/夜灯/色温/自定义颜色）：与开关、亮度一起持久化，
           # 面板据此回显当前是怎么亮的，也让只调亮度的命令不必猜颜色（#27）
           'light_mode', 'light_temp', 'light_rgb', 'light_count',
           # 美的空调（红外遥控）：都是"已收到 ACK 的指令状态"，与其它执行器一样持久保留
           'ac_status', 'ac_mode', 'ac_temperature', 'ac_fan',
           'ac_swing_ud', 'ac_swing_lr', 'ac_eco', 'ac_fzc', 'ac_timer')

# 光照明暗二态的回差边界：与 automation/engine.py 的
# SmartHomeEngine.LIGHT_DARK_RAW / LIGHT_BRIGHT_RAW 必须保持一致，
# 历史接口据此给每个采样点补 light_dark 标注，避免前端另行定义而口径不一。
LIGHT_DARK_RAW = 730
LIGHT_BRIGHT_RAW = 670


def utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')


def age_seconds(value):
    """UTC naive 时间串距今多少秒；解析不了就返回 None（别让页面瞎猜新鲜度）。"""
    text = str(value or '').strip().replace('T', ' ')[:26]
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            when = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return max(0.0, (datetime.now(timezone.utc).replace(tzinfo=None) - when).total_seconds())
    return None


def normalize_uid(value):
    uid = re.sub(r'[\s:-]', '', str(value or '')).upper()
    if len(uid) not in (8, 14, 20) or not re.fullmatch(r'[0-9A-F]+', uid):
        raise ValueError('RFID UID 必须为 4、7 或 10 字节十六进制卡号')
    return ' '.join(uid[i:i+2] for i in range(0, len(uid), 2))


# 人员表里可以分开录入/清除的凭证列（姓名之外，门禁只认这两样）
CREDENTIAL_COLUMNS = ('face_id', 'rfid_uid')


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
    # 原始遥测 1 秒一行 ≈ 8.6 万行/天；超过保留期的先聚合进 sensor_hourly
    # 再删原始行，防派上磁盘写满导致入库整体停摆。
    HISTORY_RETENTION_DAYS = 7
    _MAINTENANCE_INTERVAL_S = 3600.0

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
        self._last_maintenance = 0.0
        self.init_database()
        # 不能在 init_database 的事务里调：同一进程第二个连接会被
        # 自己的 BEGIN IMMEDIATE 锁到超时
        try:
            self.run_history_maintenance()
        except Exception:                                # noqa: BLE001
            logger.exception('[历史维护] 启动时清理失败（不影响运行）')

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
            # v3 是破坏性的「删列」，单独再备份一次
            if version < 3 and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_status'").fetchone():
                backup_path = self.db_path + '.before-v3.bak'
                if not Path(backup_path).exists():
                    with sqlite3.connect(backup_path) as backup:
                        c.backup(backup)
            c.execute('BEGIN IMMEDIATE')
            c.execute('''CREATE TABLE IF NOT EXISTS system_status (
                id INTEGER PRIMARY KEY CHECK(id=1), temperature REAL, humidity REAL,
                fan_speed INTEGER,
                door_status TEXT, window_status TEXT, light_status TEXT,
                light_brightness INTEGER, last_updated TEXT)''')
            # fan_level / light_level 是旧 B 板 state 帧的原始电平列，V2.1 裁剪后
            # 已无任何写入方，不再建（老库里的历史列留着不影响）
            extra = {k: 'INTEGER' for k in ('light_raw','smoke','rain','distance','touch','motion','soil_moisture','soil_dry','device_uptime_ms',
                                            'ac_swing_ud','ac_swing_lr','ac_eco','ac_fzc')}
            extra.update({k: 'TEXT' for k in ('buzzer_status','sensor_last_seen','output_last_seen',
                                              'ac_status','ac_mode','ac_fan')})
            # B 板硬件回读（P1）：与上面的「命令下发值」并列存放。两者不一致就说明
            # 指令没真正落到硬件上（"面板 0% 但风扇在转"这类静默失效），面板据此告警。
            extra.update({k: 'INTEGER' for k in ('rb_fan_speed','rb_light_brightness')})
            extra.update({k: 'TEXT' for k in ('rb_door_status','rb_window_status',
                                              'rb_buzzer_status','rb_seen_at')})
            extra.update({k: 'REAL' for k in ('ac_temperature','ac_timer')})
            # 灯的「亮法」（#27）：除白光/夜灯外还有色温与自定义颜色，B 板一条命令
            # 只认一种。mode 记是哪一种，temp/rgb 只在对应 mode 下有值，所以库里
            # 不会出现「色温和颜色同时有效」的矛盾行。
            extra.update({'light_count': 'INTEGER', 'light_mode': 'TEXT', 'light_rgb': 'TEXT',
                          'light_temp': 'INTEGER'})
            columns = {r['name'] for r in c.execute('PRAGMA table_info(system_status)')}
            for key, kind in extra.items():
                if key not in columns:
                    c.execute(f'ALTER TABLE system_status ADD COLUMN {key} {kind}')
            c.execute('INSERT OR IGNORE INTO system_status(id) VALUES(1)')
            if version < 2:
                keys = list(SENSORS) + list(OUTPUTS) + ['last_updated','sensor_last_seen','output_last_seen']
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
                'face_events': "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, face_id TEXT, person_name TEXT, confidence REAL, score REAL, detection_confidence REAL, image_path TEXT, device_source TEXT, status TEXT DEFAULT 'pending', verified INTEGER DEFAULT 0",
                'sensor_history': 'id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT NOT NULL, device_uptime_ms INTEGER, temperature REAL, humidity REAL, light_raw INTEGER, smoke INTEGER, rain INTEGER, distance INTEGER, touch INTEGER, motion INTEGER, soil_moisture INTEGER, soil_dry INTEGER',
                'hardware_events': 'id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT NOT NULL, module TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL',
                'automation_logs': 'id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, rule_id TEXT NOT NULL, rule_name TEXT NOT NULL, triggered INTEGER NOT NULL, conditions_hold INTEGER NOT NULL, reason TEXT, success INTEGER NOT NULL DEFAULT 0, detail_json TEXT',
                'sensor_hourly': 'hour_start TEXT PRIMARY KEY, temperature REAL, humidity REAL, light_raw REAL, samples INTEGER NOT NULL',
            }
            for table, definition in definitions.items():
                c.execute(f'CREATE TABLE IF NOT EXISTS {table} ({definition})')
            additions = {'authorized_persons': {'rfid_uid':'TEXT', 'enabled':'INTEGER NOT NULL DEFAULT 0'},
                         'access_logs': {'credential':'TEXT', 'command_status':'TEXT', 'deny_reason':'TEXT'},
                         'face_events': {'deny_reason':'TEXT', 'score':'REAL',
                                         'detection_confidence':'REAL'},
                         'sensor_hourly': {'light_raw':'REAL'}}
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
            if version < 3:
                # 空调是早期大模型幻觉产物（Module B 从来没有空调执行器）。
                # API/前端已全局删除，这里把两列也物理删掉，否则 /api/status
                # 会继续把它们原样回传给前端。
                if sqlite3.sqlite_version_info >= (3, 35, 0):
                    cols = {r['name'] for r in c.execute('PRAGMA table_info(system_status)')}
                    for col in ('ac_status', 'ac_temperature'):
                        if col in cols:
                            c.execute(f'ALTER TABLE system_status DROP COLUMN {col}')
                else:
                    logger.warning(
                        '[DB] SQLite %s 不支持 DROP COLUMN，保留已废弃的空调列'
                        '（已无任何代码引用）', sqlite3.sqlite_version)
            c.execute('PRAGMA user_version=3')

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
            # 传感器是连续遥测：过期清空。执行器字段是"已收到 ACK 的指令状态"
            # （V2.1 的 B 板不主动上报 state），必须持久保留，否则门/灯状态在
            # 最后一条指令 15 秒后全部变 null，页面无法回显真实硬件状态。
            if module == 'sensor' and not online:
                for field in fields:
                    result[field] = None
        # light_rgb 在库里存成 "r,g,b" 文本；对外一律给三元列表。/api/status 是公开
        # 契约，前端与 HA 都不该去猜存储格式（#27：文本直接让页面的颜色恢复逻辑失效）。
        # 畸形值降级成 None：这个接口被面板每秒轮询，不能因为一列脏数据抛 500。
        if isinstance(result.get('light_rgb'), str):
            try:
                parts = result['light_rgb'].split(',')
                result['light_rgb'] = [int(v) for v in parts] if len(parts) == 3 else None
            except ValueError:
                result['light_rgb'] = None
        return result

    def update_status(self, **kwargs):
        # Compatibility API; HTTP control routes must never call this optimistically.
        allowed = set(SENSORS + OUTPUTS) | {
            'sensor_last_seen', 'output_last_seen'}
        values = {k:v for k,v in kwargs.items() if k in allowed}
        if values:
            values['last_updated'] = utcnow()
            with self.connection() as c:
                self._update(c, values)
        return self.get_current_status()

    def set_output_readback(self, values: dict, seen_at=None) -> None:
        """写入 B 板「硬件回读」快照（独立于命令下发值，便于对比出不一致）。

        values 用 rb_ 前缀列；只接受白名单键，空输入直接忽略（不写坏数据）。
        """
        allowed = {'rb_fan_speed', 'rb_door_status', 'rb_window_status',
                   'rb_light_brightness', 'rb_buzzer_status'}
        data = {k: v for k, v in (values or {}).items() if k in allowed}
        if not data:
            return
        data['rb_seen_at'] = seen_at or utcnow()
        data['output_last_seen'] = data['rb_seen_at']
        with self.connection() as c:
            self._update(c, data)

    def ingest_sensor(self, message):
        if message.get('module') != 'sensor' or message.get('type') != 'data':
            raise ValueError('非 A 板数据')
        data = message['data']
        # 列级容错：单字段越界/类型错只把该列写 NULL，整帧必须入库并照常
        # 喂给仪表盘与自动化引擎。丢整帧等于无声丢数据，排查不到。
        rejected = []

        def clean(value, low, high, integer=False, field=''):
            try:
                return number(value, low, high, integer)
            except ValueError as exc:
                rejected.append(f'{field}:{exc}')
                return None

        values = {'temperature': clean(data.get('temperature'), -50, 100, field='temperature'),
                  'humidity': clean(data.get('humidity'), 0, 100, field='humidity')}
        for name, source, maximum in [('light_raw', 'light', 1023),
                                      ('distance', 'distance', 400),
                                      ('soil_moisture', 'soil_moisture', 1023)]:
            values[name] = clean(data.get(source), 0, maximum, True, field=name) if source in data else None
        for name in ('smoke', 'rain', 'touch', 'motion', 'soil_dry'):
            if name in data:
                try:
                    values[name] = boolean(data[name])
                except ValueError as exc:
                    rejected.append(f'{name}:{exc}')
                    values[name] = None
            else:
                values[name] = None
        uptime = clean(message.get('timestamp'), 0, 4294967295, True, field='timestamp')
        if rejected:
            logger.warning('[入库] 丢弃坏字段但保留整帧: %s', '; '.join(rejected))
        seen = utcnow()
        with self.connection() as c:
            sample = {'received_at':seen,'device_uptime_ms':uptime,**values}
            c.execute('INSERT INTO sensor_history('+','.join(sample)+') VALUES('+','.join('?' for _ in sample)+')',tuple(sample.values()))
            c.execute('INSERT INTO temperature_history(timestamp,temperature,humidity) VALUES(?,?,?)',(seen,values['temperature'],values['humidity']))
            self._update(c, {**values,'sensor_last_seen':seen,'device_uptime_ms':uptime,'last_updated':seen})
        self._maybe_maintenance()

    def run_history_maintenance(self):
        """把超过保留期的原始遥测聚合进 sensor_hourly，然后删除原始行。

        每小时最多跑一次（_maybe_maintenance 触发 + 启动时一次）。聚合幂等：
        同一小时重算用 INSERT OR REPLACE 覆盖，先聚合后删除，中途崩溃不丢数据。
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(
            days=self.HISTORY_RETENTION_DAYS)).strftime('%Y-%m-%d %H:00:00')
        self._last_maintenance = time.monotonic()
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute(
                "INSERT OR REPLACE INTO sensor_hourly"
                "(hour_start,temperature,humidity,light_raw,samples) "
                "SELECT strftime('%Y-%m-%d %H:00:00',timestamp),"
                "AVG(temperature),AVG(humidity),NULL,COUNT(*) "
                "FROM temperature_history "
                "WHERE source='hardware' AND timestamp<? GROUP BY 1",
                (cutoff,))
            # sensor_history 是 A 板原始快照，光照 ADC 只存在这里。温湿度聚合仍以
            # temperature_history 为准，避免改变旧库兼容逻辑；这里只补同小时光照均值。
            c.execute(
                "UPDATE sensor_hourly SET light_raw=("
                "SELECT AVG(s.light_raw) FROM sensor_history s "
                "WHERE strftime('%Y-%m-%d %H:00:00',s.received_at)="
                "sensor_hourly.hour_start AND s.received_at<?) "
                "WHERE hour_start IN (SELECT DISTINCT "
                "strftime('%Y-%m-%d %H:00:00',received_at) "
                "FROM sensor_history WHERE received_at<?)",
                (cutoff, cutoff))
            deleted_th = c.execute(
                "DELETE FROM temperature_history "
                "WHERE source='hardware' AND timestamp<?", (cutoff,)).rowcount
            deleted_sh = c.execute(
                'DELETE FROM sensor_history WHERE received_at<?',
                (cutoff,)).rowcount
            # R13：automation_logs 只增不删会长到很大（detail_json 记完整动作序列）。
            # 与原始遥测同一保留期，顺手清掉过期执行日志。
            deleted_al = c.execute(
                'DELETE FROM automation_logs WHERE timestamp<?',
                (cutoff,)).rowcount
        if deleted_th or deleted_sh or deleted_al:
            logger.info('[历史维护] 聚合截止 %s：temperature_history 删 %d 行、'
                        'sensor_history 删 %d 行、automation_logs 删 %d 行（保留 %d 天）',
                        cutoff, deleted_th, deleted_sh, deleted_al,
                        self.HISTORY_RETENTION_DAYS)

    def _maybe_maintenance(self):
        if (time.monotonic() - self._last_maintenance
                >= self._MAINTENANCE_INTERVAL_S):
            try:
                self.run_history_maintenance()
            except Exception:                            # noqa: BLE001
                logger.exception('[历史维护] 周期清理失败（不影响入库）')

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
        hours = max(1, min(int(hours), 720))
        since = (datetime.now(timezone.utc)-timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        if hours > self.HISTORY_RETENTION_DAYS * 24:
            # 已归档的小时与尚未清理的原始数据共同覆盖整个窗口。
            # 清理按完整小时迁移，正常情况下两部分的小时不会重叠。
            return self._rows(
                "SELECT hour_start AS timestamp, temperature, humidity, samples "
                "FROM sensor_hourly WHERE hour_start>? UNION ALL "
                "SELECT strftime('%Y-%m-%d %H:00:00',timestamp) AS timestamp, "
                "AVG(temperature),AVG(humidity),COUNT(*) "
                "FROM temperature_history WHERE timestamp>? AND source='hardware' "
                "GROUP BY strftime('%Y-%m-%d %H:00:00',timestamp) "
                "ORDER BY timestamp DESC LIMIT 5000", (since, since))
        # Bucket the full requested range into <= 1440 intervals, ignoring NULLs.
        bucket_seconds = max(60, int(hours)*3600//1440)
        return self._rows("SELECT MIN(timestamp) timestamp, AVG(temperature) temperature, AVG(humidity) humidity FROM temperature_history WHERE timestamp>? AND source='hardware' GROUP BY CAST(strftime('%s',timestamp) AS INTEGER)/? ORDER BY timestamp DESC",(since,bucket_seconds))

    def get_sensor_history(self, hours=24):
        return self._history('sensor_history',hours)

    def get_light_level_history(self, hours=24):
        """返回环境光照 ADC 历史，而不是灯具的开关/亮度历史。

        最近 1 小时保留每秒原始读数；更长的 7 天内窗口按时间分桶，避免一次把
        数十万点送进浏览器；超过原始保留期后与 sensor_hourly 小时归档拼接。

        返回数组，元素字段：``timestamp``（ISO-8601 UTC，秒级，带 Z）、
        ``light_raw``（取整后的 ADC 值）、``samples``（该桶样本数）、
        ``light_dark``（布尔，true=暗；按引擎同款回差逐点标注，口径与
        ``light_dark`` 能力源一致，供前端做「亮/暗」呈现）。
        """
        hours = max(1, min(int(hours), 720))
        since = (datetime.now(timezone.utc)-timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        if hours > self.HISTORY_RETENTION_DAYS * 24:
            rows = self._rows(
                "SELECT strftime('%Y-%m-%dT%H:00:00Z',hour_start) AS timestamp, "
                "CAST(ROUND(light_raw) AS INTEGER) light_raw, samples "
                "FROM sensor_hourly WHERE hour_start>? UNION ALL "
                "SELECT strftime('%Y-%m-%dT%H:00:00Z',received_at) AS timestamp, "
                "CAST(ROUND(AVG(light_raw)) AS INTEGER),COUNT(*) FROM sensor_history "
                "WHERE received_at>? GROUP BY strftime('%Y-%m-%d %H:00:00',received_at) "
                "ORDER BY timestamp DESC LIMIT 5000", (since, since))
            return self._annotate_light_dark(rows)
        bucket_seconds = 1 if hours == 1 else max(5, hours*3600//5000)
        rows = self._rows(
            "SELECT strftime('%Y-%m-%dT%H:%M:%SZ',MIN(received_at)) timestamp, "
            "CAST(ROUND(AVG(light_raw)) AS INTEGER) light_raw, COUNT(*) samples "
            "FROM sensor_history WHERE received_at>? "
            "GROUP BY CAST(strftime('%s',received_at) AS INTEGER)/? "
            "ORDER BY timestamp DESC LIMIT 5000", (since, bucket_seconds))
        return self._annotate_light_dark(rows)

    @staticmethod
    def _annotate_light_dark(rows):
        """按引擎同款回差，给按时间倒序返回的光照历史逐点补 ``light_dark``。

        从最旧点往后遍历（列表倒序即时间正序）：raw≥730 判暗、raw≤670 判亮，
        回差区间内沿用上一点状态；窗口首个点就落在回差区间时用中点兜底，
        保证每个有读数的点都有明确标注。
        """
        state = None
        for row in reversed(rows):
            raw = row.get('light_raw')
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                if raw >= LIGHT_DARK_RAW:
                    state = True
                elif raw <= LIGHT_BRIGHT_RAW:
                    state = False
                elif state is None:
                    state = raw >= (LIGHT_DARK_RAW + LIGHT_BRIGHT_RAW) / 2
            row['light_dark'] = state
        return rows

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

    def add_access_log(self, person_name, access_type, status, credential=None, command_status=None, deny_reason=None):
        with self.connection() as c:
            return c.execute('INSERT INTO access_logs(timestamp,person_name,access_type,status,credential,command_status,deny_reason) VALUES(?,?,?,?,?,?,?)',
                             (utcnow(),person_name,access_type,status,credential,command_status,deny_reason)).lastrowid

    def get_authorized_persons(self):
        """当前生效的名单（鉴权用；停用的不算）。"""
        return self._rows('SELECT * FROM authorized_persons WHERE enabled=1 ORDER BY id')

    def list_persons(self):
        """门禁页用的完整名单：停用的也要列出来，否则没法再启用/删除。"""
        return self._rows('SELECT * FROM authorized_persons ORDER BY id')

    def get_person(self, person_id):
        rows = self._rows('SELECT * FROM authorized_persons WHERE id=?', (person_id,))
        return rows[0] if rows else None

    def create_person(self, name):
        """只登记姓名建人，人脸与房卡之后在门禁页分别录入。"""
        name = (name or '').strip()
        if not name:
            raise ValueError('姓名不能为空')
        try:
            with self.connection() as c:
                cur = c.execute('INSERT INTO authorized_persons(name,enabled) VALUES(?,1)', (name,))
                # 必须用本连接读回：新连接看不到还没提交的事务
                row = c.execute('SELECT * FROM authorized_persons WHERE id=?',
                                (cur.lastrowid,)).fetchone()
                return dict(row) if row else None
        except sqlite3.IntegrityError:
            raise ValueError(f'人员「{name}」已存在')

    def _set_person_credential(self, column, person_id, value):
        """设一项凭证（None=清除）。凭证被别的启用人员占用时报错，不做静默转移。"""
        if column not in CREDENTIAL_COLUMNS:
            raise ValueError(f'未知凭证列: {column}')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM authorized_persons WHERE id=?', (person_id,)).fetchone():
                return None
            if value:
                clash = c.execute(
                    f'SELECT name FROM authorized_persons WHERE id!=? AND {column}=? AND enabled=1',
                    (person_id, value)).fetchone()
                if clash:
                    raise ValueError(f'该凭证已属于「{clash["name"]}」')
            c.execute(f'UPDATE authorized_persons SET {column}=? WHERE id=?', (value, person_id))
            return dict(c.execute('SELECT * FROM authorized_persons WHERE id=?',
                                  (person_id,)).fetchone())

    def set_person_face(self, person_id, face_id):
        return self._set_person_credential('face_id', person_id, face_id)

    def set_person_rfid(self, person_id, uid):
        uid = normalize_uid(uid) if uid else None
        return self._set_person_credential('rfid_uid', person_id, uid)

    def set_person_enabled(self, person_id, enabled):
        """停用=保留凭证但不认；启用后原来的人脸/房卡照常能用。"""
        with self.connection() as c:
            c.execute('UPDATE authorized_persons SET enabled=? WHERE id=?',
                      (1 if enabled else 0, person_id))
        return self.get_person(person_id)

    def delete_person(self, person_id):
        """删掉人员行并返回它（照片目录由调用方 face_engine.forget_identity 清理）。"""
        person = self.get_person(person_id)
        if not person:
            return None
        with self.connection() as c:
            c.execute('DELETE FROM authorized_persons WHERE id=?', (person_id,))
        return person

    def diagnose(self, credential, kind):
        """鉴权判定 + 失败原因：返回 (reason, person|None)。

        页面上「被拒」必须说得出为什么 —— 只写「未知人员」时，用户分不清是没录入、
        被停用还是名单里两个人共用一个凭证，而这三种的处置方式完全不同。
        reason: matched / no_such_identity / disabled / ambiguous / bad_credential
        """
        if kind not in ('rfid','face'):
            return 'bad_credential', None
        if not credential:
            return 'no_such_identity', None
        if kind == 'rfid':
            try:
                credential = normalize_uid(credential)
            except ValueError:
                return 'bad_credential', None
            col = 'rfid_uid'
        else:
            col = 'face_id'
        rows = self._rows(f'SELECT * FROM authorized_persons WHERE {col}=?',(credential,))
        if not rows:
            return 'no_such_identity', None
        active = [r for r in rows if r.get('enabled')]
        if not active:
            return 'disabled', rows[0]
        if len(active) > 1:
            return 'ambiguous', None
        return 'matched', active[0]

    def find_authorized(self, credential, kind):
        """当前生效名单里的唯一命中；任何其它情况（未登记/停用/歧义）都不放行。"""
        reason, person = self.diagnose(credential, kind)
        return person if reason == 'matched' else None

    def get_statistics(self):
        temp = self._rows("SELECT AVG(temperature) avg,MAX(temperature) max,MIN(temperature) min,AVG(humidity) avg_humidity FROM temperature_history WHERE source='hardware' AND timestamp>datetime('now','-24 hours')")[0]
        temp = {k:round(v,2) if v is not None else None for k,v in temp.items()}
        access = self._rows("SELECT COUNT(*) total,COALESCE(SUM(status='granted'),0) granted,COALESCE(SUM(status='denied'),0) denied FROM access_logs WHERE timestamp>datetime('now','-24 hours')")[0]
        light = self._rows("SELECT COUNT(*) total_changes,COALESCE(SUM(status='on'),0) on_count FROM light_history WHERE timestamp>datetime('now','-24 hours')")[0]
        return {'temperature_24h':temp,'access_24h':access,'light_24h':light}

    def add_face_event(self, face_id, person_name=None, confidence=None,
                       image_path=None, device_source='orange_pi', score=None,
                       detection_confidence=None, status='pending', verified=False,
                       deny_reason=None):
        """记录一次人脸事件。

        score 是 ArcFace 身份相似度；detection_confidence 是 YOLO 检出置信度。
        confidence 只为兼容旧调用方保留，页面不再把它冒充 ArcFace 分数。

        判定类调用（``granted``/``denied``）应一次把最终 ``status``/``verified``/
        ``deny_reason`` 写进来：过去先插 ``pending`` 再用第二条事务更新，放行瞬间
        页面会读到中间态，进程退出时行还会永久停在 ``pending``。观测类轮次
        （太远/节流/无脸等）用 ``status='observed'``、``deny_reason=<种类>`` 留痕。
        """
        with self.connection() as c:
            return c.execute(
                'INSERT INTO face_events(timestamp,face_id,person_name,confidence,score,detection_confidence,image_path,device_source,status,verified,deny_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (utcnow(), face_id, person_name, confidence, score,
                 detection_confidence, image_path, device_source, status,
                 int(verified), deny_reason)).lastrowid

    def get_face_events(self, limit=20):
        return self._rows('SELECT * FROM face_events ORDER BY id DESC LIMIT ?',(max(1,min(int(limit),500)),))

    def get_latest_face_event(self):
        rows = self.get_face_events(1)
        if not rows:
            return None
        event = rows[0]
        # 库里存的是 UTC naive，浏览器再按本地时区算就会差 8 小时；
        # 「这条多久前」由后端算，前端只管按新鲜度决定要不要当实时判定用
        event['age_s'] = age_seconds(event.get('timestamp'))
        return event
