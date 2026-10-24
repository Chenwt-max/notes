"""Self-made public video: no lecture frames, personal paths, keys or downloads."""
import cv2
import numpy as np
import pytest


@pytest.fixture
def prepared_models(monkeypatch):
    from lecture_notes import preparation
    monkeypatch.setattr(preparation,'state',lambda:{'ready':True})


@pytest.fixture
def sample_video(tmp_path):
    path=tmp_path/'自制 示例.mp4'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),4,(640,360))
    assert writer.isOpened()
    for index in range(40):
        image=np.full((360,640,3),248,np.uint8)
        cv2.rectangle(image,(8,8),(632,50),(160,95,55),-1)
        cv2.putText(image,'PUBLIC TEST: LINEAR ALGEBRA',(20,38),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),2)
        cv2.putText(image,'X w = y' if index<20 else 'p(y | x) = sigmoid(X w)',(35,115),cv2.FONT_HERSHEY_SIMPLEX,.8,(25,25,25),2)
        if index>=10:cv2.putText(image,'Answer: w = 2',(35,200),cv2.FONT_HERSHEY_SIMPLEX,.8,(20,20,20),2)
        if index>=20:
            cv2.circle(image,(420,255),65,(25,25,25),3)
            cv2.line(image,(320,180),(530,320),(25,25,25),3)
        writer.write(image)
    writer.release()
    return path
