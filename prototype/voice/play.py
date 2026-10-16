"""Play audio files on the default output, one after the other.  python play.py arquivo1.mp3 arquivo2.mp3 ..."""
import sys
import time

import sounddevice as sd
import soundfile as sf

for path in sys.argv[1:]:
    audio, rate = sf.read(path, dtype="float32")
    print(f"tocando {path}")
    sd.play(audio, rate)
    sd.wait()
    time.sleep(0.8)
