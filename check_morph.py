"""
Validation check for face morphing video submission.
Verifies file existence, video playability, dimensions, duration, and < 100,000 bytes limit.
"""
import os
import sys
import urllib.request
import cv2

VIDEO_PATH = "morph.mp4"
REMOTE_URL = "https://24f2008937.github.io/IIT-TDS-Repo/morph.mp4"
MAX_BYTES = 100000

def test_morph():
    # 1. Local file checks
    assert os.path.exists(VIDEO_PATH), f"File {VIDEO_PATH} does not exist"
    size = os.path.getsize(VIDEO_PATH)
    print(f"Local file size: {size} bytes ({size / 1024:.2f} KB)")
    assert size < MAX_BYTES, f"File size {size} exceeds {MAX_BYTES} bytes limit!"

    # 2. Video playability and properties
    cap = cv2.VideoCapture(VIDEO_PATH)
    assert cap.isOpened(), f"Failed to open video file {VIDEO_PATH}"
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps > 0 else 0
    cap.release()

    print(f"Video resolution: {width}x{height}")
    print(f"FPS: {fps}, Frames: {frame_count}, Duration: {duration:.2f}s")
    assert frame_count >= 60, f"Expected at least 60 frames, got {frame_count}"
    assert width > 0 and height > 0, "Invalid resolution"

    # 3. Remote URL check
    req = urllib.request.Request(REMOTE_URL, method="HEAD")
    with urllib.request.urlopen(req) as resp:
        status = resp.status
        remote_size = int(resp.headers.get("Content-Length", 0))
        content_type = resp.headers.get("Content-Type", "")
        print(f"Remote URL status: {status}")
        print(f"Remote Content-Type: {content_type}")
        print(f"Remote Content-Length: {remote_size} bytes")
        assert status == 200, f"Remote returned status {status}"
        assert remote_size < MAX_BYTES, f"Remote size {remote_size} >= {MAX_BYTES}"
        assert "video" in content_type or "octet-stream" in content_type, f"Unexpected Content-Type: {content_type}"

    print("ALL CHECKS PASSED: Video is valid, playable, and strictly under 100 KB!")

if __name__ == "__main__":
    test_morph()
