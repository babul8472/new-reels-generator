#!/usr/bin/env python3
"""
Standalone script to test Hindi voiceover generation using edge-tts.
Usage:
  python test_tts.py "आपका हिंदी टेक्स्ट यहाँ लिखें।"
"""

import sys
import asyncio
import subprocess
from pathlib import Path

async def test_tts(text: str):
    output_mp3 = Path("./test_voice.mp3")
    output_wav = Path("./test_voice.wav")
    
    # Corrected Hindi Female voice
    voice = "hi-IN-SwaraNeural" 
    
    print(f"Generating TTS for: '{text}'")
    print(f"Voice: {voice}")
    
    try:
        import edge_tts
    except ImportError:
        print("Installing edge-tts...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "edge-tts"])
        import edge_tts

    try:
        # Generate MP3
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_mp3))
        print(f"✓ Saved MP3 to: {output_mp3}")
        
        # Convert to WAV using FFmpeg
        print("Converting to WAV using FFmpeg...")
        cmd_convert = [
            "ffmpeg", "-y",
            "-i", str(output_mp3),
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            str(output_wav)
        ]
        subprocess.run(cmd_convert, check=True, capture_output=True)
        print(f"✓ Saved WAV to: {output_wav}")
        
        # Measure duration
        cmd_duration = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(output_wav)
        ]
        result = subprocess.run(cmd_duration, check=True, capture_output=True, text=True)
        duration = float(result.stdout.strip())
        print(f"✓ Success! Audio Duration: {duration:.2f} seconds")
        
    except Exception as e:
        print(f"✗ Failed: {e}")

if __name__ == "__main__":
    test_text = "क्या आप जानते हैं ब्रिटिश इतिहास में छिपी है सबसे प्यारी और हैरान कर देने वाली सच्चाई?"
    if len(sys.argv) > 1:
        test_text = sys.argv[1]
        
    asyncio.run(test_tts(test_text))
