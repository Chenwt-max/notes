"""A seek after the last frame, but inside the video, must retain its final pixels."""
import cv2
import numpy as np
import pytest

from lecture_notes.media import image_at,native_frame


@pytest.fixture
def low_fps_video(tmp_path):
    path = tmp_path/'自制 低帧率.mp4'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 2, (320, 180))
    assert writer.isOpened()
    for number in range(4):
        writer.write(np.full((180,320,3), 40+number*50, np.uint8))
    writer.release()
    return path


def test_low_fps_end_seek_preserves_final_frame(low_fps_video):
    expected = image_at(low_fps_video, 1.5)
    final = image_at(low_fps_video, 1.8)
    assert np.array_equal(final, expected)


def test_recovered_native_timestamp_is_not_requested_time(low_fps_video):
    final, actual = image_at(low_fps_video, 1.8, with_timestamp=True)
    assert final.shape == (180,320,3)
    assert actual == pytest.approx(1.5, abs=.02)


def test_seek_beyond_video_is_not_replaced_by_final_frame(low_fps_video):
    with pytest.raises(ValueError, match='无法读取'):
        image_at(low_fps_video, 20)


@pytest.mark.parametrize('requested,expected',[(.8,.5),(1.3,1.),(1.8,1.5)])
def test_low_fps_terminal_capture_does_not_take_future_content(low_fps_video,requested,expected):
    capture=cv2.VideoCapture(str(low_fps_video))
    try:frame,actual=native_frame(capture,low_fps_video,requested)
    finally:capture.release()
    assert actual==pytest.approx(expected,abs=.02)
    assert np.array_equal(frame,image_at(low_fps_video,expected))


def test_strict_hd_recovery_preserves_terminal_frame_and_rejects_outside_video(low_fps_video):
    capture=cv2.VideoCapture(str(low_fps_video))
    try:
        frame,actual=native_frame(capture,low_fps_video,1.8,not_after=True)
        assert actual==pytest.approx(1.5,abs=.02)
        assert np.array_equal(frame,image_at(low_fps_video,1.5))
        with pytest.raises(ValueError,match='未使用下一页'):
            native_frame(capture,low_fps_video,20,not_after=True)
    finally:capture.release()
