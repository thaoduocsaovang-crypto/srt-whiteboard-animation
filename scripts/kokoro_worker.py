#!/usr/bin/env python3
"""Command-line adapter for the local Kokoro-Vietnamese installation."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 5:
        print("Usage: kokoro_worker.py INPUT.txt OUTPUT.wav VOICE SPEED", file=sys.stderr)
        return 2

    input_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    voice, speed_text = sys.argv[3], sys.argv[4]
    text = input_path.read_text(encoding="utf-8").strip()
    if not text:
        print("Không có nội dung lời thoại.", file=sys.stderr)
        return 2

    try:
        speed = float(speed_text)
        if speed <= 0:
            raise ValueError("Tốc độ đọc phải lớn hơn 0.")
        import soundfile as sf
        from kokoro_vietnamese import KokoroVietnamese, SAMPLE_RATE

        # The upstream package transparently falls back from CUDA to CPU when
        # CUDA is unavailable. KOKORO_DEVICE=cpu is useful on machines where
        # CPU inference is preferred.
        device = os.environ.get("KOKORO_DEVICE", "cuda").strip().lower() or "cuda"
        if device not in {"cpu", "cuda"}:
            raise ValueError("KOKORO_DEVICE chỉ nhận 'cpu' hoặc 'cuda'.")
        tts = KokoroVietnamese(device=device, voice=voice)
        audio, _phonemes = tts.synthesize(text, speed=speed, normalize_peak=0.95)
        if len(audio) == 0:
            raise RuntimeError("Kokoro-Vietnamese không sinh được mẫu âm thanh.")
        sf.write(output_path, audio, SAMPLE_RATE)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not output_path.is_file() or output_path.stat().st_size < 44:
        print("Kokoro-Vietnamese không trả về tệp WAV hợp lệ.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
