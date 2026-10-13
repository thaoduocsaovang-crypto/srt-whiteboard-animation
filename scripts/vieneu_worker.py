#!/usr/bin/env python3
"""VieNeu command adapter for synthesis and local voice enrollment.

The profile JSON written by ``clone`` contains only the speaker embedding and
reference codes extracted by VieNeu. The original uploaded recording is never
kept by this worker.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _tts():
    from vieneu import Vieneu
    return Vieneu(backend="onnx")


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Không có nội dung lời thoại.")
    return text


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def clone(reference_path: Path, profile_path: Path, name: str) -> None:
    if not reference_path.is_file():
        raise ValueError("Không tìm thấy file thu âm tham chiếu.")
    if not name.strip():
        raise ValueError("Tên giọng không được để trống.")
    tts = _tts()
    # VieNeu cleans noise and extracts speaker embedding + reference codes.
    # save=False prevents writes into the installed VieNeu package.
    tts.add_voice(name, str(reference_path), denoise=True, save=False)
    profile = tts.get_preset_voice(name)
    if not isinstance(profile, dict) or profile.get("speaker_emb") is None:
        raise RuntimeError("VieNeu không trích xuất được hồ sơ giọng từ file thu âm.")
    _write_json(profile_path, {
        "format": "srt-vieneu-voice-profile-v1",
        "name": name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "voice": {
            "description": profile.get("description", "Giọng clone cá nhân"),
            "gender": profile.get("gender", ""),
            "style": profile.get("style", "tu_nhien"),
            "speaker_emb": [float(item) for item in profile["speaker_emb"].reshape(-1)],
            "codes": None if profile.get("codes") is None else profile["codes"].astype(int).tolist(),
        },
    })


def synthesize(input_path: Path, output_path: Path, voice_name: str, profile_path: Path | None) -> None:
    text = _read_text(input_path)
    tts = _tts()
    voice: str | dict = voice_name
    if profile_path is not None:
        if not profile_path.is_file():
            raise ValueError("Không tìm thấy hồ sơ giọng clone đã chọn.")
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        profile = data.get("voice") if isinstance(data, dict) else None
        if not isinstance(profile, dict) or not isinstance(profile.get("speaker_emb"), list):
            raise ValueError("Hồ sơ giọng clone không hợp lệ.")
        import numpy as np
        voice = {
            "speaker_emb": np.asarray(profile["speaker_emb"], dtype=np.float32),
            "codes": None if profile.get("codes") is None else np.asarray(profile["codes"], dtype=np.int64),
        }
    audio = tts.infer(text, voice=voice)
    if len(audio) == 0:
        raise RuntimeError("VieNeu-TTS không sinh được mẫu âm thanh.")
    tts.save(audio, str(output_path))
    if not output_path.is_file() or output_path.stat().st_size < 44:
        raise RuntimeError("VieNeu-TTS không trả về tệp WAV hợp lệ.")


def main() -> int:
    try:
        command = sys.argv[1] if len(sys.argv) > 1 else ""
        if command == "clone" and len(sys.argv) == 5:
            clone(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
        elif command == "synthesize" and len(sys.argv) in {5, 6}:
            profile = Path(sys.argv[5]) if len(sys.argv) == 6 else None
            synthesize(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], profile)
        # Backwards compatibility for older direct calls.
        elif len(sys.argv) == 4:
            synthesize(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], None)
        else:
            print("Usage: vieneu_worker.py synthesize INPUT.txt OUTPUT.wav VOICE [PROFILE.json]", file=sys.stderr)
            print("   or: vieneu_worker.py clone REFERENCE.wav PROFILE.json NAME", file=sys.stderr)
            return 2
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
