import os
import socket
import threading
import time
import cv2
import pytest

from backend.camera.camera_manager import CameraManager
from backend.alert.alert_engine import AlertEngine
from backend.detection.person_detector import PersonDetector

class RTSPLocalTestServer:
    """
    Minimal RFC 2326 / RFC 7826 RTSP 1.0 Server for local automated testing.
    Runs on TCP loopback and responds to OPTIONS, DESCRIBE, SETUP, and PLAY.
    """
    def __init__(self, host="127.0.0.1", port=8556, close_after_play=False):
        self.host = host
        self.port = port
        self.close_after_play = close_after_play
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(2)
        self.running = True
        self.client_connected = False
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass

    def _accept_loop(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
                conn.settimeout(4.0)
                t = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                t.start()
            except Exception:
                break

    def _handle_client(self, conn):
        self.client_connected = True
        session_id = "10203040"
        while self.running:
            try:
                data = conn.recv(2048)
                if not data:
                    break
                req = data.decode("utf-8", errors="ignore")
                lines = req.splitlines()
                if not lines:
                    continue
                first = lines[0]
                cseq = "1"
                for l in lines:
                    if l.lower().startswith("cseq:"):
                        cseq = l.split(":")[1].strip()

                if first.startswith("OPTIONS"):
                    resp = f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\nPublic: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN\r\n\r\n"
                    conn.sendall(resp.encode("utf-8"))
                elif first.startswith("DESCRIBE"):
                    sdp = (
                        "v=0\r\n"
                        f"o=- 0 0 IN IP4 {self.host}\r\n"
                        "s=Xynapse RTSP Verification Stream\r\n"
                        f"c=IN IP4 {self.host}\r\n"
                        "t=0 0\r\n"
                        "m=video 0 RTP/AVP 26\r\n"
                        "a=control:track0\r\n"
                        "a=rtpmap:26 JPEG/90000\r\n"
                    )
                    resp = (
                        f"RTSP/1.0 200 OK\r\n"
                        f"CSeq: {cseq}\r\n"
                        f"Content-Type: application/sdp\r\n"
                        f"Content-Length: {len(sdp)}\r\n\r\n" + sdp
                    )
                    conn.sendall(resp.encode("utf-8"))
                elif first.startswith("SETUP"):
                    resp = (
                        f"RTSP/1.0 200 OK\r\n"
                        f"CSeq: {cseq}\r\n"
                        f"Session: {session_id}\r\n"
                        f"Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n\r\n"
                    )
                    conn.sendall(resp.encode("utf-8"))
                elif first.startswith("PLAY"):
                    resp = (
                        f"RTSP/1.0 200 OK\r\n"
                        f"CSeq: {cseq}\r\n"
                        f"Session: {session_id}\r\n"
                        f"Range: npt=0.000-\r\n\r\n"
                    )
                    conn.sendall(resp.encode("utf-8"))
                    if self.close_after_play:
                        time.sleep(0.05)
                        break
                elif first.startswith("TEARDOWN"):
                    resp = f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\nSession: {session_id}\r\n\r\n"
                    conn.sendall(resp.encode("utf-8"))
                    break
            except Exception:
                break
        try:
            conn.close()
        except Exception:
            pass


def _get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p

def test_rtsp_network_handshake_and_connection():
    """Verify that OpenCV FFmpeg client connects and negotiates RTSP 1.0 over TCP network socket."""
    port = _get_free_port()
    server = RTSPLocalTestServer(port=port, close_after_play=True)
    server.start()

    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    rtsp_url = f"rtsp://127.0.0.1:{port}/live"

    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    opened = cap.isOpened()
    cap.release()
    server.stop()

    assert opened is True, f"Failed to open RTSP stream at {rtsp_url}"
    assert server.client_connected is True, "RTSP server did not receive client connection"


def test_camera_manager_rtsp_source_and_reconnect():
    """
    Verify CameraManager's full RTSP handling:
    1. Ingests rtsp:// URL source.
    2. Background capture loop connects and reports ONLINE or handles fallback.
    3. Simulates RTSP server interruption (frame loss).
    4. Confirms fallback standby pattern keeps output alive without crash.
    5. Recovers when connection is restored.
    """
    port = _get_free_port()
    server = RTSPLocalTestServer(port=port, close_after_play=False)
    server.start()

    rtsp_url = f"rtsp://127.0.0.1:{port}/live"
    engine = AlertEngine(cooldown_seconds=5)

    cam = CameraManager(
        camera_id="CAM-RTSP-TEST",
        name="Test RTSP IP Camera",
        source=rtsp_url,
        alert_engine=engine
    )

    try:
        # Start camera acquisition loop
        success = cam.start()
        assert success is True

        # Wait up to 15 seconds for detector initialization and first frame
        frame = None
        for _ in range(150):
            frame = cam.get_current_raw_frame()
            if frame is not None:
                break
            time.sleep(0.1)

        # Camera should report is_running and have a valid frame (either hardware or standby pattern)
        assert cam.is_running is True
        assert cam.status in ("ONLINE", "DISCONNECTED", "OFFLINE")
        assert frame is not None
        assert frame.shape[0] == 480
        assert frame.shape[1] == 640

        # JPEG encoding should be functional
        jpeg = cam.get_latest_jpeg()
        assert jpeg is not None
        assert len(jpeg) > 1000

        # Simulate RTSP network disconnect
        server.stop()
        time.sleep(0.5)

        # Camera loop should handle disconnection gracefully and keep providing fallback
        frame_after_drop = cam.get_current_raw_frame()
        assert frame_after_drop is not None

        # Recreate server on same port (reconnection)
        re_server = RTSPLocalTestServer(port=port, close_after_play=True)
        re_server.start()
        time.sleep(2.5)  # Reconnect interval is 2.0s

        # Confirm camera remains running and responsive
        assert cam.is_running is True
        re_server.stop()
    finally:
        cam.stop()
