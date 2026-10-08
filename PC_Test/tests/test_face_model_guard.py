"""换嵌入模型的安全网：模型指纹校验、库重建入口、路径来源。

跑法（无需真模型/摄像头/串口）：
    python -m unittest discover -s PC_Test/tests -v

这些用例守的是同一个事故：换了 recognition 模型但 embeddings.pkl 还是旧模型算的原型。
跨模型余弦相似度实测只有 0.077（见 docs/face-models.md），不拦的话服务照常启动、
日志一句不错，只是谁都进不了门。
"""
import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.config import PC_TEST_DIR, RECOGNITION_MODEL_PATH
from web.face import engine as engine_mod
from web.face.engine import FaceEngine
from web.face.recognizer import (FaceRecognizer, build_embedding_database,
                                 FACE_PREPROCESSING_VERSION,
                                 LEGACY_PREPROCESSING_VERSION,
                                 model_fingerprint, normalize_embedding)


def make_engine(web_face_cfg: dict, config_path: Path) -> FaceEngine:
    """模拟模式引擎：不加载 YOLO，只用来测配置与库校验逻辑。"""
    return FaceEngine(config_path=str(config_path),
                      web_cfg={"face": web_face_cfg,
                               "serial": {"enabled": False}})


def stub_recognizer(method="arcface_onnx", library_fp="", current_model=None,
                    preprocessing=FACE_PREPROCESSING_VERSION):
    """够用的识别器替身：引擎只读这三个属性做校验。"""
    class Stub:
        def __init__(self):
            self.method = method
            self.identities = [{"name": "A"}, {"name": "B"}]
            self.library_fingerprint = library_fp
            self.model_fingerprint = model_fingerprint(method, current_model)
            self.library_preprocessing = preprocessing
    return Stub()


class FingerprintTests(unittest.TestCase):
    def test_non_model_method_needs_no_file(self):
        self.assertEqual(model_fingerprint("simple_grayscale_cosine", None),
                         "simple_grayscale_cosine")

    def test_missing_file_is_recorded_not_crashed(self):
        fp = model_fingerprint("arcface_onnx", Path(tempfile.gettempdir()) / "nope.onnx")
        self.assertEqual(fp, "arcface_onnx:missing")

    def test_different_files_get_different_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.onnx"
            second = Path(tmp) / "b.onnx"
            first.write_bytes(b"MODEL-A" + b"\x00" * 4096)
            second.write_bytes(b"MODEL-B" + b"\x00" * 4096)
            fp_first = model_fingerprint("arcface_onnx", first)
            fp_second = model_fingerprint("arcface_onnx", second)
            self.assertNotEqual(fp_first, fp_second)
            # 同一文件重复计算必须一致，否则每次重启都会误判成「库过期了」
            self.assertEqual(fp_first, model_fingerprint("arcface_onnx", first))
            self.assertTrue(fp_first.startswith("arcface_onnx:"))


class DatabaseFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, bias in (("甲", 30), ("乙", 200)):
            person = self.root / "authorized" / name
            person.mkdir(parents=True)
            for idx in range(2):
                frame = numpy.full((64, 64, 3), bias + idx * 3, dtype=numpy.uint8)
                self.assertTrue(cv2.imwrite(str(person / f"{idx}.jpg"), frame))

    def test_build_database_stamps_fingerprint(self):
        database = build_embedding_database(
            authorized_dir=self.root / "authorized",
            method="simple_grayscale_cosine", model_path=None)
        self.assertEqual(database["model_fingerprint"], "simple_grayscale_cosine")
        self.assertEqual(database["preprocessing"], LEGACY_PREPROCESSING_VERSION)
        self.assertEqual(len(database["identities"]), 2)

    def test_recognizer_exposes_both_fingerprints(self):
        database = build_embedding_database(
            authorized_dir=self.root / "authorized",
            method="simple_grayscale_cosine", model_path=None)
        pkl = self.root / "embeddings.pkl"
        with pkl.open("wb") as file:
            pickle.dump(database, file)
        recognizer = FaceRecognizer(embeddings_path=pkl, model_path=None)
        self.assertEqual(recognizer.library_fingerprint, "simple_grayscale_cosine")
        self.assertEqual(recognizer.model_fingerprint, "simple_grayscale_cosine")

    def test_legacy_database_has_no_fingerprint(self):
        pkl = self.root / "legacy.pkl"
        with pkl.open("wb") as file:
            pickle.dump({"version": 2, "method": "simple_grayscale_cosine",
                         "image_size": 112,
                         "identities": [{"name": "甲",
                                         "prototype": [1.0, 0.0],
                                         "image_count": 1}]}, file)
        recognizer = FaceRecognizer(embeddings_path=pkl, model_path=None)
        self.assertEqual(recognizer.library_fingerprint, "")


class LibraryModelGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "face_config.json"
        self.engine = make_engine({"simulation_mode": True,
                                   "recognition": {"method": "arcface_onnx"}},
                                  self.config_path)

    def test_matching_fingerprint_leaves_recognition_on(self):
        self.engine.simulation_mode = False
        self.engine.recognizer = stub_recognizer(current_model=None)
        self.engine.recognizer.model_fingerprint = "arcface_onnx:100:aaa"
        self.engine.recognizer.library_fingerprint = "arcface_onnx:100:aaa"
        self.engine._check_library_model()
        self.assertIsNone(self.engine.recognition_block)
        self.assertIsNone(self.engine.model_mismatch())
        self.assertEqual(self.engine.get_status()["mode"], "recognition")

    def test_mismatch_blocks_recognition_and_reports_both(self):
        self.engine.simulation_mode = False
        self.engine.recognizer = stub_recognizer(current_model=None)
        self.engine.recognizer.model_fingerprint = "arcface_onnx:9:新模型"
        self.engine.recognizer.library_fingerprint = "arcface_onnx:174383860:旧模型"
        self.engine._check_library_model()
        self.assertIsNotNone(self.engine.recognition_block)
        self.assertEqual(self.engine.model_mismatch(),
                         {"library": "arcface_onnx:174383860:旧模型",
                          "current": "arcface_onnx:9:新模型"})
        status = self.engine.get_status()
        self.assertTrue(status["recognition"]["blocked"])
        # 停用认人但不停用检测：mode 退回 yolov8，门禁只是不放行
        self.assertEqual(status["mode"], "yolov8")

    def test_legacy_arcface_preprocessing_is_blocked(self):
        rec = stub_recognizer(
            library_fp="arcface_onnx:100:aaa",
            preprocessing=LEGACY_PREPROCESSING_VERSION)
        rec.model_fingerprint = rec.library_fingerprint
        self.engine.recognizer = rec
        self.engine._check_library_model()
        self.assertIn("五点对齐", self.engine.recognition_block)
        self.assertIn("重建人脸库", self.engine.recognition_block)

    def test_legacy_library_keeps_working_without_stampede(self):
        """老库没记指纹：按当前模型继续认人，不能因为升级就把门停了。"""
        self.engine.recognizer = stub_recognizer(library_fp="")
        with self.assertLogs("web.face.engine", level="WARNING") as captured:
            self.engine._check_library_model()
        self.assertIsNone(self.engine.recognition_block)
        self.assertTrue(any("没记模型指纹" in line for line in captured.output))

    def test_hot_apply_refreshes_recorded_fingerprint(self):
        """录完脸热加载：状态里的库指纹要跟着新库走，不能还停在启动时读到的那份。"""
        rec = stub_recognizer(library_fp="")
        self.engine.recognizer = rec
        self.engine._apply_database({"version": 2, "method": rec.method,
                                     "model_fingerprint": "arcface_onnx:9:新指纹",
                                     "preprocessing": FACE_PREPROCESSING_VERSION,
                                     "image_size": 112,
                                     "identities": [{"name": "甲", "prototype": [1.0]}]})
        self.assertEqual(rec.library_fingerprint, "arcface_onnx:9:新指纹")
        self.assertEqual(rec.library_preprocessing, FACE_PREPROCESSING_VERSION)
        self.assertEqual(
            self.engine.get_status()["recognition"]["library_fingerprint"],
            "arcface_onnx:9:新指纹")

    def test_enroll_refuses_mixed_library(self):
        self.engine.simulation_mode = False
        self.engine.detector = object()
        self.engine.recognition_block = "人脸库由模型 X 建立，当前模型是 Y"
        result = self.engine.enroll_faces("丙", ["aaaa"])
        self.assertFalse(result["ok"])
        self.assertIn("模型", result["error"])
        # 拒绝得趁早：目录都不该建出来，否则留下没原型的空身份
        self.assertFalse((engine_mod.AUTHORIZED_DIR / "丙").exists())

    def test_recognizer_load_failure_is_visible(self):
        """识别器建不起来（模型文件没就位最常见）也得在状态里说清楚，别静默降级。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkl = root / "embeddings.pkl"
            with pkl.open("wb") as file:
                pickle.dump({"version": 2, "method": "arcface_onnx", "image_size": 112,
                             "model_fingerprint": "arcface_onnx:1:zzz",
                             "identities": [{"name": "甲", "prototype": [1.0],
                                             "image_count": 1}]}, file)
            detector_model = root / "face.pt"
            detector_model.write_bytes(b"stub")
            self.engine.config["model_path"] = str(detector_model)
            self.engine.simulation_mode = False
            with patch.object(engine_mod, "EMBEDDINGS_PATH", pkl), \
                    patch("web.face.detector.YOLOFaceDetector"), \
                    patch("web.face.recognizer.FaceRecognizer",
                          side_effect=FileNotFoundError("Recognition model not found")):
                self.engine._load_model()
            self.assertIsNone(self.engine.recognizer)
            self.assertIn("不可用", self.engine.recognition_block)
            self.assertIn("不可用",
                          self.engine.get_status()["recognition"]["block_reason"])

    def test_model_mismatch_needs_no_extra_state(self):
        self.engine.recognizer = None
        self.engine.recognition_block = "随便什么原因"
        self.assertIsNone(self.engine.model_mismatch())


class LegacyLibraryProbeTests(unittest.TestCase):
    """老库没写 model_fingerprint：拿注册照重算原型自检。

    派上现存的库正是这种库。光留一行 warning 的话，「换了模型没重建库」就还是
    那个服务照常启动、日志一句不错、谁都进不了门的静默故障。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.authorized = self.root / "authorized"
        for name, bias in (("甲", 30), ("乙", 200)):
            person = self.authorized / name
            person.mkdir(parents=True)
            for idx in range(2):
                frame = numpy.full((64, 64, 3), bias + idx * 3, dtype=numpy.uint8)
                cv2.imwrite(str(person / f"{idx}.jpg"), frame)
        self.pkl = self.root / "embeddings.pkl"
        patcher = patch.object(engine_mod, "AUTHORIZED_DIR", self.authorized)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build_legacy(self, rewrite=None):
        """照片建库 → 抹掉指纹 → 当老库加载；rewrite 用来模拟别的模型算出的原型。"""
        database = build_embedding_database(
            authorized_dir=self.authorized,
            method="simple_grayscale_cosine", model_path=None)
        database.pop("model_fingerprint")
        if rewrite:
            for identity in database["identities"]:
                identity["prototype"] = rewrite(identity["name"], identity["prototype"])
        with self.pkl.open("wb") as file:
            pickle.dump(database, file)
        recognizer = FaceRecognizer(embeddings_path=self.pkl, model_path=None)
        self.assertEqual(recognizer.library_fingerprint, "")
        engine = make_engine({"simulation_mode": True,
                              "recognition": {"method": "simple_grayscale_cosine"}},
                             self.root / "face_config.json")
        engine.simulation_mode = False
        engine.recognizer = recognizer
        return engine, recognizer

    def saved(self):
        with self.pkl.open("rb") as file:
            return pickle.load(file)

    def test_verified_library_is_stamped_and_stays_on(self):
        engine, rec = self.build_legacy()
        with self.assertLogs("web.face.engine", level="INFO") as captured:
            engine._check_library_model()
        self.assertIsNone(engine.recognition_block)
        self.assertEqual(rec.library_fingerprint, rec.model_fingerprint)
        # 指纹落盘：下次启动不必再花这笔提特征的钱
        self.assertEqual(self.saved()["model_fingerprint"], rec.model_fingerprint)
        self.assertTrue(any("自检通过" in line for line in captured.output))
        self.assertEqual(engine.get_status()["mode"], "recognition")

    def test_cross_model_legacy_library_is_blocked(self):
        """原型换成与照片几乎正交的向量（跨模型的实测表现）→ 停用认人并给出原因。"""
        rng = numpy.random.default_rng(7)

        def other_model(_name, prototype):
            noise = rng.standard_normal(len(prototype)).astype(numpy.float32)
            return normalize_embedding(noise)

        engine, rec = self.build_legacy(rewrite=other_model)
        with self.assertLogs("web.face.engine", level="ERROR"):
            engine._check_library_model()
        self.assertIn("重建人脸库", engine.recognition_block)
        self.assertTrue(engine.get_status()["recognition"]["blocked"])
        # 没有可比对的指纹，不能冒充「两份指纹不一致」那条 i18n 句子
        self.assertIsNone(engine.model_mismatch())
        self.assertNotIn("model_fingerprint", self.saved())

    def test_inconclusive_similarity_keeps_recognition_on(self):
        """落在判定区之间（注册照可能不是人脸裁片）：继续认人，只告警、不写盘。"""
        rng = numpy.random.default_rng(11)

        def partly(_name, prototype):
            noise = normalize_embedding(
                rng.standard_normal(len(prototype)).astype(numpy.float32))
            vector = 0.42 * numpy.asarray(prototype, dtype=numpy.float32) + \
                0.908 * noise
            return normalize_embedding(vector)

        engine, rec = self.build_legacy(rewrite=partly)
        with self.assertLogs("web.face.engine", level="WARNING") as captured:
            engine._check_library_model()
        self.assertIsNone(engine.recognition_block)
        self.assertEqual(rec.library_fingerprint, "")
        self.assertNotIn("model_fingerprint", self.saved())
        self.assertTrue(any("自检" in line for line in captured.output))

    def test_missing_photos_are_not_a_verdict(self):
        engine, rec = self.build_legacy()
        for path in self.authorized.rglob("*.jpg"):
            path.unlink()
        with self.assertLogs("web.face.engine", level="WARNING") as captured:
            engine._check_library_model()
        self.assertIsNone(engine.recognition_block)
        self.assertEqual(rec.library_fingerprint, "")
        self.assertTrue(any("自检" in line for line in captured.output))


class RecognitionModelPathTests(unittest.TestCase):
    """模型文件路径只认 web_config.yaml，换模型/回滚都只改那一行。"""

    def _path(self, web_recog: dict) -> Path:
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine({"simulation_mode": True, "recognition": web_recog},
                                 Path(tmp) / "face_config.json")
            return engine.recognition_model_path

    def test_relative_yaml_path_resolves_against_pc_test_dir(self):
        self.assertEqual(
            self._path({"model_path": "models/face/w600k_mbf.onnx"}),
            PC_TEST_DIR / "models" / "face" / "w600k_mbf.onnx")

    def test_absolute_yaml_path_is_used_as_is(self):
        absolute = Path(tempfile.gettempdir()) / "x.onnx"
        self.assertEqual(self._path({"model_path": str(absolute)}), absolute)

    def test_missing_yaml_entry_falls_back_to_default(self):
        self.assertEqual(self._path({}), RECOGNITION_MODEL_PATH)

    def test_stale_face_config_json_path_does_not_win(self):
        """data/face/face_config.json 里那条绝对路径（往往是另一台机器写的）不作数。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "face_config.json"
            config_path.write_text(
                '{"simulation_mode": true, "recognition": '
                '{"model_path": "D:\\\\Projects\\\\other\\\\recognition.onnx"}}',
                encoding="utf-8")
            engine = make_engine({"simulation_mode": True,
                                  "recognition": {"model_path": "models/face/w600k_mbf.onnx"}},
                                 config_path)
            self.assertEqual(engine.recognition_model_path,
                             PC_TEST_DIR / "models" / "face" / "w600k_mbf.onnx")


class EmptyDatabaseTests(unittest.TestCase):
    def test_new_library_carries_current_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine({"simulation_mode": True,
                                  "recognition": {"method": "simple_grayscale_cosine",
                                                  "model_path": ""}},
                                 Path(tmp) / "face_config.json")
            database = engine._empty_database("simple_grayscale_cosine", 112)
            self.assertEqual(database["model_fingerprint"], "simple_grayscale_cosine")
            self.assertEqual(database["preprocessing"], FACE_PREPROCESSING_VERSION)
            self.assertEqual(database["version"], 2)
            self.assertEqual(database["identities"], [])

    def test_prototype_vector_is_normalized(self):
        vector = normalize_embedding(numpy.array([3.0, 4.0], dtype="float32"))
        self.assertAlmostEqual(float((vector ** 2).sum()), 1.0, places=6)


class DiagnosticsEndpointTests(unittest.TestCase):
    """门禁体检页必须说得出「为什么一张脸都认不出」。"""

    KEYS = ("SMART_HOME_ADMIN_USER", "SMART_HOME_ADMIN_PASSWORD_HASH",
            "SMART_HOME_SESSION_SECRET", "SMART_HOME_SERVICE_TOKEN")

    def setUp(self):
        # 环境变量是给 create_app 用的，测完必须还原：留着假哈希会咬坏后面的登录用例
        self._saved = {key: os.environ.get(key) for key in self.KEYS}
        os.environ.update(
            SMART_HOME_ADMIN_USER="test-admin",
            SMART_HOME_ADMIN_PASSWORD_HASH=generate_password_hash("test-password"),
            SMART_HOME_SESSION_SECRET="s" * 48,
            SMART_HOME_SERVICE_TOKEN="t" * 48)
        from web.api import access
        self.access = access

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _diagnostics(self, mismatch):
        from web.app import create_app
        app = create_app({"serial": {"enabled": False}}, start_hardware=False)
        app.testing = True
        client = app.test_client()
        with client.session_transaction() as session:
            session["user"] = "test-admin"
        with patch.object(self.access, "face_engine") as face:
            face.library_identities.return_value = ["A"]
            face.config = {"known_faces": {}}
            face.recognition_block = "人脸库由模型 X 建立" if mismatch else None
            face.model_mismatch.return_value = mismatch
            response = client.get("/api/access/diagnostics")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_mismatch_is_reported(self):
        payload = self._diagnostics({"library": "旧", "current": "新"})
        self.assertEqual(payload["model_mismatch"], {"library": "旧", "current": "新"})
        self.assertEqual(payload["recognition_block"], "人脸库由模型 X 建立")

    def test_no_mismatch_key_is_null(self):
        payload = self._diagnostics(None)
        self.assertIsNone(payload["model_mismatch"])
        self.assertIsNone(payload["recognition_block"])


if __name__ == "__main__":
    unittest.main()
