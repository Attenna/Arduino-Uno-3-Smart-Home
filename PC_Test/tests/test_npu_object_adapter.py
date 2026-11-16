import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import cv2
import numpy as np
from web.object_detection import ObjectDetector


class NpuAdapterTests(unittest.TestCase):
    def setup_detector(self, directory):
        model = Path(directory) / 'model.onnx'
        model.write_bytes(b'test-model')
        session = Mock()
        session.get_modelmeta.return_value.custom_metadata_map = {'names': "{0:'drone',1:'fire extinguisher',2:'light bulb'}"}
        session.get_inputs.return_value = [Mock(name='input')]
        session.get_inputs.return_value[0].name = 'images'
        session.get_inputs.return_value[0].shape = [1,3,640,640]
        session.get_outputs.return_value = [Mock()]
        session.get_outputs.return_value[0].shape = [1,7,8400]
        output = np.zeros((1,7,8400),np.float32)
        output[0,:,0] = [320,320,100,100,0,0,.9]
        session.run.return_value = [output]
        with patch('onnxruntime.InferenceSession',return_value=session):
            detector = ObjectDetector(model)
        ok, jpeg = cv2.imencode('.jpg',np.zeros((640,640,3),np.uint8))
        self.assertTrue(ok)
        return detector, output, jpeg.tobytes()

    def test_npu_and_cpu_share_preprocessing_and_boxes(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ',{'SMART_HOME_NPU_URL':'','SMART_HOME_NPU_TOKEN':''}):
                cpu, output, jpeg = self.setup_detector(directory)
                expected = cpu.detect(jpeg)['detections']
            with patch.dict('os.environ',{'SMART_HOME_NPU_URL':'http://private-npu:8093','SMART_HOME_NPU_TOKEN':'x'*40}):
                npu, _, jpeg = self.setup_detector(directory)
                with patch('requests.post',return_value=Mock(status_code=200,content=output.tobytes())) as post:
                    actual = npu.detect(jpeg)['detections']
                    self.assertEqual(actual,expected)
                    self.assertEqual(len(post.call_args.kwargs['data']),1*3*640*640*4)
                    self.assertEqual(npu.info()['provider'],'Ascend310B4')

    def test_invalid_npu_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'SMART_HOME_NPU_URL':'http://private-npu:8093','SMART_HOME_NPU_TOKEN':'x'*40}):
            npu, _, jpeg = self.setup_detector(directory)
            with patch('requests.post',return_value=Mock(status_code=200,content=b'bad')):
                with self.assertRaises(RuntimeError):npu.detect(jpeg)
            with patch('requests.post',return_value=Mock(status_code=503)):
                with self.assertRaises(RuntimeError):npu.detect(jpeg)
