"""YOLOv8 face ONNX decoding, including optional five-point pose outputs."""
import os
import cv2
import numpy as np
from ..npu_client import infer_npu
from .detector import FaceDetection


class AscendFaceDetector:
    def __init__(self, confidence, iou, image_size):
        if image_size != 640:
            raise ValueError('当前人脸NPU模型输入尺寸为640')
        self.confidence, self.iou = confidence, iou
        self.url = os.environ['SMART_HOME_FACE_DETECTOR_NPU_URL']
        self.token = os.environ.get('SMART_HOME_NPU_TOKEN','')
        self.channels = int(os.environ.get('SMART_HOME_FACE_DETECTOR_CHANNELS','20'))
        if self.channels not in (5,20):
            raise ValueError('需要单类人脸检测或五点姿态输出')

    def detect(self, image):
        if image is None or image.size == 0:
            return []
        height,width=image.shape[:2]
        ratio=min(640/width,640/height)
        resized_width,resized_height=round(width*ratio),round(height*ratio)
        left,top=(640-resized_width)//2,(640-resized_height)//2
        canvas=np.full((640,640,3),114,dtype=np.uint8)
        canvas[top:top+resized_height,left:left+resized_width]=cv2.resize(image,(resized_width,resized_height))
        tensor=np.ascontiguousarray(canvas[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255
        rows=infer_npu(self.url,self.token,tensor,(1,self.channels,8400))[0].T
        rows=rows[rows[:,4]>=self.confidence]
        boxes=[]
        for row in rows:
            cx,cy,bw,bh=row[:4]
            boxes.append([float(cx-bw/2),float(cy-bh/2),float(bw),float(bh)])
        keep=cv2.dnn.NMSBoxes(boxes,rows[:,4].tolist(),self.confidence,self.iou)
        detections=[]
        for index in np.asarray(keep).reshape(-1)[:300]:
            row=rows[int(index)]
            x,y,bw,bh=boxes[int(index)]
            bbox=(float(np.clip((x-left)/ratio,0,width)),float(np.clip((y-top)/ratio,0,height)),
                  float(np.clip((x+bw-left)/ratio,0,width)),float(np.clip((y+bh-top)/ratio,0,height)))
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            points=None
            if self.channels==20:
                raw=row[5:].reshape(5,3)
                xy=(raw[:,:2]-np.asarray([left,top],np.float32))/ratio
                xy[:,0]=np.clip(xy[:,0],0,width)
                xy[:,1]=np.clip(xy[:,1],0,height)
                if not np.allclose(xy,0) and not np.any(np.all(np.isclose(xy,0),axis=1)):
                    points=tuple((float(p[0]),float(p[1])) for p in xy)
            detections.append(FaceDetection(bbox,float(row[4]),0,'face',points))
        return detections
