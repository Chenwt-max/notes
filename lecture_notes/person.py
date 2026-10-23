"""Local YOLOX person boxes, used only to compare unobstructed course content.

Pre/postprocessing adapted from YOLOX's ONNX demo (Megvii, Apache-2.0).
Modified here for person-only detection and explicit CPU/CUDA providers.
"""
from functools import lru_cache

import cv2
import numpy as np

from .common import MODELS
from .resources import cpu_threads,inference_device

MODEL_SHA256 = '427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7'
MODEL_CONFIGS = {
    'yolox-tiny':('yolox_tiny.onnx',MODEL_SHA256),
    'yolox-s':('yolox_s.onnx','c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'),
}


@lru_cache(maxsize=2)
def detector(model_name='yolox-tiny'):
    import onnxruntime as ort
    filename,expected = MODEL_CONFIGS[model_name]
    path = MODELS/filename
    if not path.exists():
        if model_name!='yolox-tiny':
            raise ValueError('增强人物模型未准备，请运行 scripts/升级本地模型.ps1')
        return None
    import hashlib
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError('人物模型校验失败，请重新运行 scripts/prepare_person.py')
    options = ort.SessionOptions()
    options.intra_op_num_threads = cpu_threads()
    options.add_session_config_entry("session.intra_op.allow_spinning","0")
    providers = ['CPUExecutionProvider']
    if inference_device()=='cuda':
        from .asr import cuda_libraries
        cuda_libraries()
        if 'CUDAExecutionProvider' in ort.get_available_providers():
            providers.insert(0,('CUDAExecutionProvider',{'cudnn_conv_algo_search':'HEURISTIC','gpu_mem_limit':2*1024**3}))
    return ort.InferenceSession(str(path), options, providers=providers)


def person_mask(image,model_name='yolox-tiny'):
    session = detector(model_name)
    mask = np.zeros(image.shape[:2], np.uint8)
    if session is None:
        return None, []
    height, width = image.shape[:2]
    size = session.get_inputs()[0].shape[2]
    ratio = min(size/height, size/width)
    padded = np.full((size, size, 3), 114, np.uint8)
    padded[:int(height*ratio), :int(width*ratio)] = cv2.resize(image, (int(width*ratio), int(height*ratio)))
    tensor = np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)[None]
    prediction = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
    grids, scales = [], []
    for stride in (8, 16, 32):
        yy, xx = np.mgrid[:size//stride, :size//stride]
        grids.append(np.stack((xx, yy), -1).reshape(-1, 2))
        scales.extend([stride]*(size//stride)**2)
    scale = np.asarray(scales)[:, None]
    centers = (prediction[:, :2]+np.concatenate(grids))*scale/ratio
    sizes = np.exp(prediction[:, 2:4])*scale/ratio
    scores = prediction[:, 4]*prediction[:, 5]  # COCO class 0: person
    selected = scores > .3
    boxes = np.concatenate((centers-sizes/2, sizes), axis=1)[selected]
    scores = scores[selected]
    kept = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), .3, .45)
    found = []
    for index in np.asarray(kept).reshape(-1):
        x, y, w, h = boxes[index]
        # Small padding covers hands at the box edge; never alter source pixels.
        x0, y0 = max(0, int(x-w*.04)), max(0, int(y-h*.02))
        x1, y1 = min(width, int(x+w*1.04)), min(height, int(y+h*1.02))
        mask[y0:y1, x0:x1] = 1
        found.append({'box': [x0, y0, x1, y1], 'score': float(scores[index])})
    return mask, found


def edge_occluders(image, reference):
    """Catch a partial hand/arm entering at the edge, which box detectors miss.

    Require a connected moving area containing skin colour and touching an edge.
    Text and white chalk alone cannot satisfy the skin-colour condition.
    """
    hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    skin = (hsv[:,:,0]<27)&(hsv[:,:,1]>50)&(hsv[:,:,1]<220)&(hsv[:,:,2]>55)
    if np.count_nonzero(skin)<30:
        return np.zeros(image.shape[:2],np.uint8)
    moving = np.uint8(np.max(cv2.absdiff(image,reference),axis=2)>25)
    moving = cv2.morphologyEx(moving,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    count,labels,stats,_ = cv2.connectedComponentsWithStats(moving)
    mask = np.zeros(moving.shape,np.uint8)
    h,w = moving.shape
    for index in range(1,count):
        x,y,cw,ch,area = stats[index]
        if (x<3 or y+ch>h-3 or x+cw>w-3) and 100<area<.23*h*w:
            component = labels==index
            if np.count_nonzero(component & skin)>30:
                mask[component] = 1
    return cv2.dilate(mask,np.ones((5,5),np.uint8))
