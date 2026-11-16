import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from web.face.detector import YOLOFaceDetector


class FaceNpuAdapterTests(unittest.TestCase):
    def test_pose_coordinates_restore_letterbox_and_five_points(self):
        output=np.zeros((1,20,8400),np.float32)
        output[0,:5,0]=[320,320,200,280,.9]
        output[0,5:,0]=[270,270,.99,370,270,.99,320,320,.99,285,370,.99,355,370,.99]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'SMART_HOME_FACE_DETECTOR_NPU_URL':'http://npu','SMART_HOME_NPU_TOKEN':'x'*40}):
            model=Path(folder)/'face.pt';model.write_bytes(b'fixture')
            detector=YOLOFaceDetector(model)
            with patch('web.face.ascend_detector.infer_npu',return_value=output):
                faces=detector.detect(np.zeros((360,640,3),np.uint8))
            self.assertEqual(len(faces),1)
            self.assertEqual(faces[0].xyxy_int(),(220,40,420,320))
            self.assertEqual(faces[0].landmarks[0],(270,130))
            self.assertEqual(detector.provider,'Ascend310B4')

    def test_zero_keypoint_preserves_crop_fallback(self):
        output=np.zeros((1,20,8400),np.float32)
        output[0,:5,0]=[320,320,200,200,.9]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'SMART_HOME_FACE_DETECTOR_NPU_URL':'http://npu','SMART_HOME_NPU_TOKEN':'x'*40}):
            model=Path(folder)/'face.pt';model.write_bytes(b'fixture')
            detector=YOLOFaceDetector(model)
            with patch('web.face.ascend_detector.infer_npu',return_value=output):
                faces=detector.detect(np.zeros((640,640,3),np.uint8))
            self.assertIsNone(faces[0].landmarks)
