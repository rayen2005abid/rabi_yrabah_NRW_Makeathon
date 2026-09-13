from src.video_source import parse_video_source


def test_parse_local_camera_index_from_string():
    parsed = parse_video_source("2")
    assert parsed.value == 2
    assert parsed.is_network is False


def test_parse_http_phone_stream():
    parsed = parse_video_source("http://192.168.1.50:8080/video")
    assert parsed.value == "http://192.168.1.50:8080/video"
    assert parsed.is_network is True


def test_parse_rtsp_phone_stream():
    parsed = parse_video_source("rtsp://192.168.1.50:8554/live")
    assert parsed.is_network is True
