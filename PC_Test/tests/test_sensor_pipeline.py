"""温湿度入库链路回归：列级容错、保留+聚合、硬件桥入库计数。

不连真实串口：桥测试用假 db，DB 测试用临时库文件。
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from web.database import SmartHomeDB


def frame(ts=12345, **overrides):
    data = {"temperature": 25.0, "humidity": 50.0, "light": 100,
            "smoke": False, "rain": True, "motion": False}
    data.update(overrides)
    return {"module": "sensor", "type": "data", "timestamp": ts, "data": data}


class IngestToleranceTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = SmartHomeDB(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            p = Path(self.path + suffix)
            if p.exists():
                p.unlink()

    def test_normal_frame(self):
        self.db.ingest_sensor(frame())
        status = self.db.get_current_status()
        self.assertEqual(status["temperature"], 25.0)
        self.assertEqual(status["humidity"], 50.0)
        self.assertEqual(status["light_raw"], 100)
        self.assertTrue(status["sensor_online"])

    def test_light_level_history_keeps_each_one_second_sample(self):
        now = datetime.now(timezone.utc)
        with self.db.connection() as c:
            c.execute("INSERT INTO sensor_history(received_at,light_raw) VALUES(?,?)",
                      ((now - timedelta(seconds=2)).strftime('%Y-%m-%d %H:%M:%S'), 321))
            c.execute("INSERT INTO sensor_history(received_at,light_raw) VALUES(?,?)",
                      ((now - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S'), 654))
        rows = self.db.get_light_level_history(hours=1)
        self.assertEqual([row["light_raw"] for row in rows], [654.0, 321.0])
        self.assertEqual([row["samples"] for row in rows], [1, 1])

    def test_out_of_range_field_nulls_only_that_column(self):
        # 温度毛刺 999：整帧必须照入库，只把 temperature 列写 NULL
        self.db.ingest_sensor(frame(temperature=999))
        rows = self.db.get_sensor_history(hours=1)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["temperature"])
        self.assertEqual(rows[0]["humidity"], 50.0)
        status = self.db.get_current_status()
        self.assertIsNone(status["temperature"])
        self.assertEqual(status["humidity"], 50.0)

    def test_bad_type_and_bad_uptime_keep_frame(self):
        self.db.ingest_sensor(frame(temperature="abc", motion="yes"))
        rows = self.db.get_sensor_history(hours=1)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["temperature"])
        self.assertIsNone(rows[0]["motion"])
        self.db.ingest_sensor(frame(ts="nan", humidity=61))
        rows = self.db.get_sensor_history(hours=1)
        self.assertEqual(len(rows), 2)
        # get_sensor_history 按时间倒序：最新帧是 rows[0]
        self.assertIsNone(rows[0]["device_uptime_ms"])
        self.assertEqual(rows[0]["humidity"], 61.0)

    def test_non_sensor_message_still_rejected(self):
        with self.assertRaises(ValueError):
            self.db.ingest_sensor({"module": "output", "type": "data",
                                   "timestamp": 1, "data": {}})


class RetentionTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = SmartHomeDB(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            p = Path(self.path + suffix)
            if p.exists():
                p.unlink()

    def test_old_rows_aggregated_then_deleted(self):
        old = (datetime.now(timezone.utc) - timedelta(days=8)).strftime('%Y-%m-%d %H:%M:%S')
        with self.db.connection() as c:
            c.execute("INSERT INTO temperature_history(timestamp,temperature,humidity,source)"
                      " VALUES(?,20.0,40.0,'hardware')", (old,))
            c.execute("INSERT INTO temperature_history(timestamp,temperature,humidity,source)"
                      " VALUES(?,22.0,44.0,'hardware')", (old,))
            c.execute("INSERT INTO sensor_history(received_at,temperature,humidity,light_raw)"
                      " VALUES(?,20.0,40.0,200)", (old,))
        self.db.ingest_sensor(frame())  # 新鲜行
        self.db.run_history_maintenance()

        with self.db.connection() as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM temperature_history "
                          "WHERE source='hardware' AND timestamp<=?", (old,)).fetchone()[0], 0)
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM sensor_history WHERE received_at<=?",
                          (old,)).fetchone()[0], 0)
            hourly = c.execute("SELECT * FROM sensor_hourly").fetchall()
        self.assertEqual(len(hourly), 1)
        self.assertAlmostEqual(hourly[0]["temperature"], 21.0)
        self.assertAlmostEqual(hourly[0]["light_raw"], 200.0)
        self.assertEqual(hourly[0]["samples"], 2)

        # 超过保留窗口必须同时包含归档小时与最近的原始数据。
        agg = self.db.get_temperature_history(hours=24 * 14)
        self.assertEqual(len(agg), 2)
        self.assertEqual([row['temperature'] for row in agg], [25.0, 21.0])
        self.assertEqual(sum(row['samples'] for row in agg), 3)
        fresh = self.db.get_temperature_history(hours=1)
        self.assertEqual(len(fresh), 1)

        # 再次维护不能重复归档或丢掉已有小时。
        self.db.run_history_maintenance()
        self.assertEqual(self.db.get_temperature_history(hours=24 * 14), agg)
        light_agg = self.db.get_light_level_history(hours=24 * 14)
        self.assertEqual([row['light_raw'] for row in light_agg], [100.0, 200.0])

    def test_long_window_with_only_recent_samples(self):
        self.db.ingest_sensor(frame(temperature=23, humidity=48))
        rows = self.db.get_temperature_history(hours=720)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['temperature'], 23)
        self.assertEqual(rows[0]['samples'], 1)


class BridgeIngestStatsTests(unittest.TestCase):
    class FakeDB:
        def __init__(self, fail=False):
            self.frames = []
            self.fail = fail

        def ingest_sensor(self, message):
            if self.fail:
                raise sqlite_error()
            self.frames.append(message)

    def _bridge(self, fake_db):
        from web.hardware import McpHardwareBridge
        return McpHardwareBridge({"serial": {"enabled": False}}, fake_db)

    def test_counts_and_dedup(self):
        fake = self.FakeDB()
        bridge = self._bridge(fake)
        bridge._ingest_snapshot({"timestamp": 100, "temperature": 20})
        bridge._ingest_snapshot({"timestamp": 100, "temperature": 20})  # 重复帧跳过
        bridge._ingest_snapshot({"timestamp": 101, "temperature": 21})
        stats = bridge.ingest_stats
        self.assertEqual(stats["ok"], 2)
        self.assertEqual(stats["fail"], 0)
        self.assertEqual(len(fake.frames), 2)

    def test_default_polling_matches_one_second_sensor_reports(self):
        bridge = self._bridge(self.FakeDB())
        self.assertEqual(bridge.poll_interval, 1.0)

    def test_failure_is_counted_not_swallowed(self):
        fake = self.FakeDB(fail=True)
        bridge = self._bridge(fake)
        bridge._ingest_snapshot({"timestamp": 100, "temperature": 20})
        stats = bridge.ingest_stats
        self.assertEqual(stats["fail"], 1)
        self.assertTrue(stats["last_error"])
        # 失败帧不推进水位线，恢复后同一帧还能再试
        fake.fail = False
        bridge._ingest_snapshot({"timestamp": 100, "temperature": 20})
        self.assertEqual(bridge.ingest_stats["ok"], 1)


def sqlite_error():
    import sqlite3
    return sqlite3.OperationalError("database is locked")


if __name__ == '__main__':
    unittest.main()
