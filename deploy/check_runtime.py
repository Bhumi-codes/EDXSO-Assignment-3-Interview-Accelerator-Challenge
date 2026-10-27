"""Verify audio dependencies during deployment; no provider/database requests."""
import io
from pathlib import Path
import sys
import wave
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import av
from app.pause_detection import model
buffer = io.BytesIO()
with wave.open(buffer, "wb") as audio:
    audio.setnchannels(1)
    audio.setsampwidth(2)
    audio.setframerate(16000)
    audio.writeframes(bytes(32000))
with av.open(io.BytesIO(buffer.getvalue())) as container:
    assert sum(frame.samples for frame in container.decode(audio=0)) == 16000
assert model().get_providers() == ["CPUExecutionProvider"]
print("Audio decoding and CPU pause-detection model loaded successfully.")
