#!/usr/bin/env python3
"""Máy chủ cục bộ cho Preview Desk và chức năng xuất MP4.

Chỉ lắng nghe tại 127.0.0.1. Trình duyệt gửi ảnh cảnh hiện tại cùng annotation
qua JSON; dữ liệu tạm được xóa ngay sau khi renderer tạo xong MP4.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# In a PyInstaller one-file build, static files are unpacked to ``_MEIPASS``.
# Keep source-mode paths unchanged so the developer workflow still runs from
# this checkout exactly as before.
SOURCE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
ROOT = BUNDLED_ROOT
# Bundled files are read-only and temporary.  Keep voice profiles in the
# user's application-data directory when running the portable EXE.
if getattr(sys, "frozen", False):
    _app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    TTS_ROOT = _app_data / "SRT Whiteboard Animation" / "tts-runtime"
    CUSTOM_VOICE_DIR = _app_data / "SRT Whiteboard Animation" / "vieneu-custom-voices"
else:
    TTS_ROOT = SOURCE_ROOT
    CUSTOM_VOICE_DIR = SOURCE_ROOT / "data" / "vieneu-custom-voices"
KOKORO_WORKER = TTS_ROOT / "scripts" / "kokoro_worker.py"
KOKORO_PYTHON = TTS_ROOT / ".venv-kokoro" / "Scripts" / "python.exe"
VIENEU_WORKER = TTS_ROOT / "scripts" / "vieneu_worker.py"
VIENEU_PYTHON = TTS_ROOT / ".venv-vtts" / "Scripts" / "python.exe"
CUSTOM_VOICE_INDEX = CUSTOM_VOICE_DIR / "voices.json"
CUSTOM_VOICE_LOCK = threading.Lock()
MAX_REQUEST_BYTES = 30 * 1024 * 1024
MAX_PROJECT_REQUEST_BYTES = 200 * 1024 * 1024
RENDER_LOCK = threading.Lock()
TTS_LOCK = threading.Lock()
PROJECT_RENDER_STATUS: dict[str, dict] = {}
PROJECT_RENDER_STATUS_LOCK = threading.Lock()


def _ensure_tts_runtime(engine: str) -> None:
    """Install an optional TTS engine into per-user app data on first use."""
    python = KOKORO_PYTHON if engine == "kokoro" else VIENEU_PYTHON
    if python.is_file():
        return
    installer_name = "install_kokoro.ps1" if engine == "kokoro" else "install_vieneu.ps1"
    installer = ROOT / "scripts" / installer_name
    if not installer.is_file():
        raise RuntimeError("Không tìm thấy bộ cài TTS trong gói ứng dụng.")
    # Files in a one-file EXE live in a temporary, read-only extraction folder.
    # Copy the bootstrap scripts to persistent per-user storage before setup.
    TTS_ROOT.mkdir(parents=True, exist_ok=True)
    bundled_scripts = ROOT / "scripts"
    target_scripts = TTS_ROOT / "scripts"
    shutil.copytree(bundled_scripts, target_scripts, dirs_exist_ok=True)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target_scripts / installer_name)],
        cwd=str(TTS_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
    )
    if result.returncode != 0 or not python.is_file():
        detail = (result.stderr or result.stdout or "Không rõ lỗi").strip()[-1800:]
        raise RuntimeError(f"Không thể tự cài {engine}. Cần Internet ở lần đầu.\n{detail}")


def _read_custom_voices() -> list[dict]:
    """Return the small public index; profiles stay server-side."""
    if not CUSTOM_VOICE_INDEX.is_file():
        return []
    try:
        data = json.loads(CUSTOM_VOICE_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    voices = data.get("voices", []) if isinstance(data, dict) else []
    return [item for item in voices if isinstance(item, dict)
            and isinstance(item.get("id"), str) and isinstance(item.get("name"), str)
            and isinstance(item.get("profile"), str)]


def _write_custom_voices(voices: list[dict]) -> None:
    CUSTOM_VOICE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CUSTOM_VOICE_INDEX.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": 1, "voices": voices}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CUSTOM_VOICE_INDEX)


class AppHandler(SimpleHTTPRequestHandler):
    """Phục vụ giao diện và nhận yêu cầu dựng một cảnh."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/render-progress":
            job_id = parse_qs(parsed.query).get("jobId", [""])[0]
            with PROJECT_RENDER_STATUS_LOCK:
                status = PROJECT_RENDER_STATUS.get(job_id, {"state": "unknown"})
            self._send_json(HTTPStatus.OK, status)
            return
        if parsed.path == "/api/tts-voices":
            with CUSTOM_VOICE_LOCK:
                voices = [{"id": item["id"], "name": item["name"]} for item in _read_custom_voices()]
            self._send_json(HTTPStatus.OK, {"voices": voices})
            return
        super().do_GET()

    def do_POST(self) -> None:
        endpoint = urlparse(self.path).path
        if endpoint == "/api/tts":
            self._generate_tts()
            return
        if endpoint == "/api/voice-clone":
            self._clone_voice()
            return
        if endpoint not in {"/api/render", "/api/render-project"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Không tìm thấy API")
            return
        payload: dict = {}
        try:
            if endpoint == "/api/render-project":
                payload = self._read_json(MAX_PROJECT_REQUEST_BYTES)
                scenes = payload.get("scenes")
                total = len(scenes) if isinstance(scenes, list) else 0
                self._set_project_status(payload.get("jobId", ""), "starting", 0, total)
                output_name, video = self._render_project(payload)
            else:
                payload = self._read_json()
                output_name, video = self._render(payload)
        except ValueError as exc:
            if endpoint == "/api/render-project":
                self._set_project_status(payload.get("jobId", ""), "error", message=str(exc))
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except subprocess.TimeoutExpired:
            if endpoint == "/api/render-project":
                self._set_project_status(payload.get("jobId", ""), "error", message="timeout")
            self._send_json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "Dựng video quá thời gian chờ (10 phút)."})
            return
        except RuntimeError as exc:
            if endpoint == "/api/render-project":
                self._set_project_status(payload.get("jobId", ""), "error", message=str(exc))
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return
        except OSError as exc:
            if endpoint == "/api/render-project":
                self._set_project_status(payload.get("jobId", ""), "error", message=str(exc))
                message = f"Không thể xử lý dự án video: {exc}"
            else:
                message = f"Không thể chạy bộ sinh audio: {exc}"
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": message})
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Disposition", f'attachment; filename="{output_name}"')
        self.send_header("Content-Length", str(len(video)))
        self.end_headers()
        self.wfile.write(video)

    @staticmethod
    def _set_project_status(job_id: str, state: str, current: int = 0, total: int = 0,
                            scene: str = "", message: str = "") -> None:
        if not isinstance(job_id, str) or not job_id:
            return
        with PROJECT_RENDER_STATUS_LOCK:
            if len(PROJECT_RENDER_STATUS) > 32:
                oldest = sorted(PROJECT_RENDER_STATUS, key=lambda key: PROJECT_RENDER_STATUS[key].get("updated", 0))[:16]
                for key in oldest:
                    PROJECT_RENDER_STATUS.pop(key, None)
            PROJECT_RENDER_STATUS[job_id] = {"state": state, "current": current, "total": total,
                                              "scene": scene, "message": message, "updated": time.time()}

    def _generate_tts(self) -> None:
        try:
            payload = self._read_json()
            text = str(payload.get("text", "")).strip()
            engine = str(payload.get("engine", "kokoro")).lower()
            speaker = str(payload.get("speaker", "diem_trinh"))
            offline = bool(payload.get("offline", False))
            if not text:
                raise ValueError("Nhập lời thoại trước khi tạo giọng đọc.")
            if len(text) > 20000:
                raise ValueError("Lời thoại vượt quá 20.000 ký tự cho một lần tạo.")
            kokoro_voices = {
                "diem_trinh", "hung_thinh", "mai_linh", "mai_loan", "manh_dung",
                "my_yen", "ngoc_huyen", "phat_tai", "thanh_dat", "thuc_trinh",
                "tuan_ngoc", "storyvert", "duc_an", "duc_duy",
            }
            vieneu_voices = {
                "Hải Đăng", "Mai Anh", "Trúc Ly", "Thiện Minh", "Thùy Dung",
                "Quang Sơn", "Ngọc Trân", "Phạm Tuyên", "Minh Đức", "Adam",
                "Thái Sơn", "Mỹ Duyên",
            }
            if engine not in {"kokoro", "vieneu"}:
                raise ValueError("Bộ máy tạo giọng không hợp lệ.")
            custom_voice = None
            if engine == "vieneu":
                with CUSTOM_VOICE_LOCK:
                    custom_voice = next((item for item in _read_custom_voices() if item["id"] == speaker), None)
                if speaker not in vieneu_voices and custom_voice is None:
                    raise ValueError("Giọng đọc không hợp lệ.")
            elif speaker not in kokoro_voices:
                raise ValueError("Giọng đọc không hợp lệ.")
            try:
                speed = float(payload.get("speed", 1.0))
            except (TypeError, ValueError) as exc:
                raise ValueError("Tốc độ đọc không hợp lệ.") from exc
            if not 0.75 <= speed <= 1.25:
                raise ValueError("Tốc độ đọc phải nằm trong khoảng 0,75–1,25.")
            if engine == "kokoro":
                python = Path(os.environ.get("KOKORO_PYTHON", str(KOKORO_PYTHON)))
                worker, label, command_tail = KOKORO_WORKER, "Kokoro-Vietnamese", [speaker, f"{speed:.2f}"]
            else:
                python = Path(os.environ.get("VIENEU_PYTHON", str(VIENEU_PYTHON)))
                worker, label = VIENEU_WORKER, "VieNeu-TTS"
                command_tail = ["synthesize", speaker]
                if custom_voice is not None:
                    profile_path = CUSTOM_VOICE_DIR / custom_voice["profile"]
                    if not profile_path.is_file():
                        raise RuntimeError("Không tìm thấy hồ sơ của giọng clone. Hãy tạo lại giọng này.")
                    command_tail.append(str(profile_path))
            if not python.is_file():
                _ensure_tts_runtime(engine)
            with tempfile.TemporaryDirectory(prefix=f"srt-{engine}-") as temp_dir:
                work = Path(temp_dir)
                input_path, output_path = work / "speech.txt", work / "speech.wav"
                input_path.write_text(text, encoding="utf-8")
                with TTS_LOCK:
                    worker_env = {**os.environ, "PYTHONUTF8": "1"}
                    if engine == "vieneu" and offline:
                        # Hugging Face honors this flag: cached local model files may
                        # be used, but no network request is allowed.
                        worker_env.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
                    result = subprocess.run(
                        [str(python), str(worker), str(input_path), str(output_path), *command_tail]
                        if engine == "kokoro" else [str(python), str(worker), "synthesize", str(input_path), str(output_path), *command_tail[1:]],
                        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                        env=worker_env,
                    )
                if result.returncode != 0 or not output_path.is_file():
                    detail = (result.stderr or result.stdout or "Không rõ lỗi").strip()[-1800:]
                    raise RuntimeError(f"{label} không tạo được audio.\n{detail}")
                audio = output_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except subprocess.TimeoutExpired:
            self._send_json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "Tạo giọng đọc quá thời gian chờ 10 phút."})
        except RuntimeError as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
        except OSError as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Không thể chạy bộ tạo giọng: {exc}"})

    def _clone_voice(self) -> None:
        """Enroll a short user-provided recording through VieNeu and retain its profile."""
        try:
            payload = self._read_json()
            name = " ".join(str(payload.get("name", "")).split())
            if not 1 <= len(name) <= 60:
                raise ValueError("Tên giọng cần từ 1 đến 60 ký tự.")
            if not bool(payload.get("acknowledged")):
                raise ValueError("Hãy xác nhận bạn có quyền sử dụng giọng trong file thu âm.")
            offline = bool(payload.get("offline", False))
            encoded = payload.get("audioDataUrl", "")
            if not isinstance(encoded, str) or not (encoded.startswith("data:audio/") or encoded.startswith("data:application/octet-stream")):
                raise ValueError("Chỉ nhận file audio WAV, MP3, M4A hoặc OGG.")
            audio = self._decode_data_url(encoded, "Không thể đọc file thu âm.")
            if not 1024 <= len(audio) <= 15 * 1024 * 1024:
                raise ValueError("File thu âm cần có dung lượng từ 1 KB đến 15 MB.")
            suffix = Path(str(payload.get("fileName", "reference.wav"))).suffix.lower()
            if suffix not in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
                suffix = ".wav"
            with CUSTOM_VOICE_LOCK:
                voices = _read_custom_voices()
                if any(item["name"].casefold() == name.casefold() for item in voices):
                    raise ValueError("Tên này đã có trong danh sách giọng. Hãy chọn tên khác.")
                voice_id = f"custom-{uuid.uuid4().hex}"
                profile_name = f"{voice_id}.json"
                profile_path = CUSTOM_VOICE_DIR / profile_name
                CUSTOM_VOICE_DIR.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="srt-vieneu-reference-") as temp_dir:
                    reference_path = Path(temp_dir) / f"reference{suffix}"
                    reference_path.write_bytes(audio)
                    normalized_reference = Path(temp_dir) / "reference.wav"
                    # libsndfile (used inside VieNeu) cannot decode M4A on Windows.
                    # ffmpeg accepts M4A/MP3/OGG/FLAC and gives VieNeu one stable WAV.
                    self._normalize_clone_audio(reference_path, normalized_reference)
                    python = Path(os.environ.get("VIENEU_PYTHON", str(VIENEU_PYTHON)))
                    if not python.is_file():
                        raise RuntimeError("Chưa cài VieNeu-TTS. Chạy scripts\\install_vieneu.ps1 rồi khởi động lại Preview Desk.")
                    result = subprocess.run(
                        [str(python), str(VIENEU_WORKER), "clone", str(normalized_reference), str(profile_path), name],
                        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                        env={**os.environ, "PYTHONUTF8": "1", **({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"} if offline else {})},
                    )
                if result.returncode != 0 or not profile_path.is_file():
                    profile_path.unlink(missing_ok=True)
                    detail = (result.stderr or result.stdout or "Không rõ lỗi").strip()[-1800:]
                    raise RuntimeError(f"VieNeu-TTS không tạo được giọng mẫu.\n{detail}")
                voices.append({"id": voice_id, "name": name, "profile": profile_name})
                _write_custom_voices(voices)
            self._send_json(HTTPStatus.OK, {"id": voice_id, "name": name})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except subprocess.TimeoutExpired:
            self._send_json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "Tạo hồ sơ giọng quá thời gian chờ 10 phút."})
        except RuntimeError as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
        except OSError as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Không thể xử lý file thu âm: {exc}"})

    def _read_json(self, max_bytes: int = MAX_REQUEST_BYTES) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= max_bytes:
            raise ValueError(f"Dữ liệu xuất không hợp lệ hoặc vượt giới hạn {max_bytes // (1024 * 1024)} MB.")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Không thể đọc dữ liệu từ giao diện.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Yêu cầu xuất không hợp lệ.")
        return payload

    def _render(self, payload: dict) -> tuple[str, bytes]:
        encoded = payload.get("imageDataUrl", "")
        audio_encoded = payload.get("audioDataUrl", "")
        profile = str(payload.get("renderProfile", "studio"))
        config = payload.get("annotation")
        scene_name = str(payload.get("sceneName", "scene")).strip() or "scene"
        if not encoded.startswith("data:image/") or "," not in encoded:
            raise ValueError("Thiếu ảnh cảnh để dựng.")
        if not isinstance(config, dict) or not config.get("elements"):
            raise ValueError("Cảnh cần ít nhất một mô-đun vẽ trước khi xuất video.")
        image_bytes = self._decode_data_url(encoded, "Dữ liệu ảnh không hợp lệ.")

        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in scene_name)[:80]
        output_name = f"{safe_name or 'scene'}-whiteboard.mp4"
        with tempfile.TemporaryDirectory(prefix="srt-whiteboard-") as temp_dir:
            work = Path(temp_dir)
            image_path = work / "scene.png"
            annotation_path = work / "scene.annotation.json"
            output_path = work / output_name
            image_path.write_bytes(image_bytes)
            annotation_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with RENDER_LOCK:
                quality_args = {
                    "draft": ["--cap-long-edge", "540", "--fps", "12"],
                    "studio": ["--cap-long-edge", "1080", "--fps", "24"],
                    "master": ["--cap-long-edge", "1920", "--fps", "30", "--ink-path", "skeleton"],
                }.get(profile, ["--cap-long-edge", "1080", "--fps", "24"])
                # Import in-process: a frozen executable cannot start itself
                # as a Python interpreter for a separate renderer script.
                from render_stream_whiteboard import main as render_main
                result_code = render_main([str(image_path), str(annotation_path), str(output_path), *quality_args])
            if result_code != 0 or not output_path.exists():
                raise RuntimeError("Không thể dựng MP4. Hãy kiểm tra ảnh và dữ liệu vùng vẽ.")
            final_path = output_path
            if audio_encoded:
                media_type = audio_encoded.split(",", 1)[0].lower()
                audio_ext = ".wav" if "wav" in media_type else ".m4a" if "mp4" in media_type or "m4a" in media_type else ".mp3"
                audio_path = work / f"voice{audio_ext}"
                audio_path.write_bytes(self._decode_data_url(audio_encoded, "Dữ liệu audio không hợp lệ."))
                final_path = self._mix_audio(output_path, audio_path, work / f"mixed-{output_name}")
            return output_name, final_path.read_bytes()

    def _render_project(self, payload: dict) -> tuple[str, bytes]:
        scenes = payload.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("Dự án chưa có cảnh nào để xuất.")
        if len(scenes) > 100:
            raise ValueError("Một lần xuất hỗ trợ tối đa 100 cảnh.")
        profile = str(payload.get("renderProfile", "studio"))
        quality_args = {
            "draft": ["--cap-long-edge", "540", "--fps", "12"],
            "studio": ["--cap-long-edge", "1080", "--fps", "24"],
            "master": ["--cap-long-edge", "1920", "--fps", "30", "--ink-path", "skeleton"],
        }.get(profile, ["--cap-long-edge", "1080", "--fps", "24"])
        project_name = str(payload.get("projectName", "project")).strip() or "project"
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in project_name)[:70] or "project"
        output_name = f"{safe_name}-final.mp4"
        job_id = payload.get("jobId", "")

        with tempfile.TemporaryDirectory(prefix="srt-whiteboard-project-") as temp_dir:
            work = Path(temp_dir)
            rendered: list[Path] = []
            for index, scene in enumerate(scenes, start=1):
                if not isinstance(scene, dict):
                    raise ValueError(f"Dữ liệu cảnh thứ {index} không hợp lệ.")
                encoded = scene.get("imageDataUrl", "")
                config = scene.get("annotation")
                if not encoded.startswith("data:image/") or "," not in encoded:
                    raise ValueError(f"Cảnh thứ {index} thiếu ảnh.")
                if not isinstance(config, dict) or not config.get("elements"):
                    raise ValueError(f"Cảnh thứ {index} cần ít nhất một mô-đun vẽ.")
                image_path = work / f"scene-{index:03d}.png"
                annotation_path = work / f"scene-{index:03d}.annotation.json"
                output_path = work / f"scene-{index:03d}.mp4"
                self._set_project_status(job_id, "rendering", index, len(scenes), str(scene.get("sceneName", f"Cảnh {index}")))
                image_path.write_bytes(self._decode_data_url(encoded, f"Ảnh cảnh thứ {index} không hợp lệ."))
                annotation_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
                with RENDER_LOCK:
                    from render_stream_whiteboard import main as render_main
                    result_code = render_main([str(image_path), str(annotation_path), str(output_path), *quality_args])
                if result_code != 0 or not output_path.is_file():
                    raise RuntimeError(f"Không thể dựng cảnh {index} ({scene.get('sceneName', 'scene')}).")
                audio_encoded = scene.get("audioDataUrl")
                if audio_encoded:
                    media_type = audio_encoded.split(",", 1)[0].lower()
                    audio_ext = ".wav" if "wav" in media_type else ".m4a" if "mp4" in media_type or "m4a" in media_type else ".mp3"
                    audio_path = work / f"scene-{index:03d}-voice{audio_ext}"
                    audio_path.write_bytes(self._decode_data_url(audio_encoded, f"Audio cảnh thứ {index} không hợp lệ."))
                    mixed_path = work / f"scene-{index:03d}-mixed.mp4"
                    self._mix_audio(output_path, audio_path, mixed_path)
                    output_path = mixed_path
                rendered.append(output_path)

            self._set_project_status(job_id, "merging", len(scenes), len(scenes))
            merged_path = work / output_name
            from merge_scenes import main as merge_main
            result_code = merge_main(["--inputs", *map(str, rendered), "--output", str(merged_path)])
            if result_code != 0 or not merged_path.is_file():
                raise RuntimeError("Không thể ghép các cảnh thành video hoàn chỉnh.")
            video = merged_path.read_bytes()
            self._set_project_status(job_id, "done", len(scenes), len(scenes))
            return output_name, video

    @staticmethod
    def _decode_data_url(value: str, error: str) -> bytes:
        if not isinstance(value, str) or "," not in value:
            raise ValueError(error)
        try:
            return base64.b64decode(value.split(",", 1)[1], validate=True)
        except ValueError as exc:
            raise ValueError(error) from exc

    @staticmethod
    def _normalize_clone_audio(input_path: Path, output_path: Path) -> Path:
        """Decode a browser upload into the WAV format VieNeu can always read."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("Không tìm thấy ffmpeg để đọc file M4A/MP3. Hãy cài ffmpeg hoặc tải lên file WAV.")
        result = subprocess.run(
            [ffmpeg, "-y", "-nostdin", "-i", str(input_path), "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(output_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size < 1024:
            detail = result.stderr.strip()[-1200:]
            raise RuntimeError(f"Không thể đọc file thu âm. Hãy thử WAV, M4A hoặc MP3 hợp lệ.\n{detail}")
        return output_path

    @staticmethod
    def _mix_audio(video_path: Path, audio_path: Path, output_path: Path) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("Không tìm thấy ffmpeg để ghép audio. Hãy cài ffmpeg rồi thử lại.")
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-shortest", "-movflags", "+faststart", str(output_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"Không thể ghép audio: {result.stderr.strip()[-1200:]}")
        return output_path

    def _send_json(self, status: HTTPStatus, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Mở Preview Desk có chức năng xuất MP4")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Mở giao diện trong trình duyệt mặc định")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), AppHandler)
    address = f"http://127.0.0.1:{args.port}/assets/preview.html"
    # A pythonw-launched server has no stdout; a console may also use cp1252.
    if sys.stdout is not None:
        print(f"Preview Desk is running at {address}", flush=True)
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
