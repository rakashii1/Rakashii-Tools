import glob
import json
import os
import subprocess
import sys
import tempfile
import uuid

import imageio_ffmpeg


DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "reclip-downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

YTDLP_CMD = [sys.executable, "-m", "yt_dlp"]
FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()


def read_json_body(request_handler):
    length = int(request_handler.headers.get("content-length", "0") or 0)
    if not length:
        return {}
    raw = request_handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def send_json(request_handler, payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    request_handler.send_response(status)
    request_handler.send_header("Content-Type", "application/json")
    request_handler.send_header("Content-Length", str(len(body)))
    request_handler.end_headers()
    request_handler.wfile.write(body)


def send_file_response(request_handler, path, filename):
    with open(path, "rb") as file:
        body = file.read()
    request_handler.send_response(200)
    request_handler.send_header("Content-Type", "application/octet-stream")
    request_handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    request_handler.send_header("Content-Length", str(len(body)))
    request_handler.end_headers()
    request_handler.wfile.write(body)


def extract_process_error(stderr):
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("ERROR:"):
            return line
    return lines[-1] if lines else "Process failed"


def parse_ytdlp_json(stdout):
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            return json.loads(line)
    raise ValueError("yt-dlp returned no data")


def get_video_info(url):
    result = subprocess.run(
        [*YTDLP_CMD, "--no-playlist", "-j", url],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(extract_process_error(result.stderr))

    info = parse_ytdlp_json(result.stdout)
    best_by_height = {}
    for item in info.get("formats", []):
        height = item.get("height")
        if height and item.get("vcodec", "none") != "none":
            tbr = item.get("tbr") or 0
            current = best_by_height.get(height)
            if not current or tbr > (current.get("tbr") or 0):
                best_by_height[height] = item

    formats = [
        {"id": item["format_id"], "label": f"{height}p", "height": height}
        for height, item in best_by_height.items()
    ]
    formats.sort(key=lambda item: item["height"], reverse=True)

    return {
        "title": info.get("title", ""),
        "thumbnail": info.get("thumbnail", ""),
        "duration": info.get("duration"),
        "uploader": info.get("uploader", ""),
        "formats": formats,
    }


def get_playlist_urls(url):
    result = subprocess.run(
        [*YTDLP_CMD, "--flat-playlist", "-J", url],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(extract_process_error(result.stderr))
    info = json.loads(result.stdout)
    return [entry.get("url") for entry in info.get("entries", []) if entry.get("url")]


def video_format_selector(format_id=None):
    if format_id:
        return f"{format_id}+bestaudio[ext=m4a]/{format_id}+bestaudio/{format_id}/best"
    return "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/bv*[vcodec^=avc1]+ba/bv*[ext=mp4]+ba[ext=m4a]/bestvideo+bestaudio/best"


def convert_to_compatible_mp4(source_path, job_id):
    fixed_path = os.path.join(DOWNLOAD_DIR, f"{job_id}-fixed.mp4")
    cmd = [
        FFMPEG_LOCATION,
        "-y",
        "-i",
        source_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        fixed_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(extract_process_error(result.stderr))
    return fixed_path


def safe_filename(title, path):
    ext = os.path.splitext(path)[1]
    if title:
        safe_title = "".join(char for char in title if char not in r'\/:*?"<>|').strip()[:100].strip()
        if safe_title:
            return f"{safe_title}{ext}"
    return os.path.basename(path)


def download_video(url, format_choice="max", format_id=None, title=""):
    job_id = uuid.uuid4().hex[:10]
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    cmd = [
        *YTDLP_CMD,
        "--no-playlist",
        "--ffmpeg-location",
        FFMPEG_LOCATION,
        "-o",
        out_template,
    ]

    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3"]
    elif format_choice == "max":
        cmd += ["-f", video_format_selector(format_id), "--merge-output-format", "mkv"]
    else:
        cmd += ["-f", video_format_selector(format_id), "--merge-output-format", "mp4"]

    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(extract_process_error(result.stderr))

    files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
    if not files:
        raise RuntimeError("Download completed but no file was found")

    if format_choice == "audio":
        target = [path for path in files if path.endswith(".mp3")]
        chosen = target[0] if target else files[0]
    elif format_choice == "max":
        media_files = [
            path
            for path in files
            if os.path.splitext(path)[1].lower() in {".mkv", ".mp4", ".webm", ".mov"}
        ]
        chosen = max(media_files or files, key=os.path.getsize)
    else:
        target = [path for path in files if path.endswith(".mp4")]
        chosen = target[0] if target else files[0]
        chosen = convert_to_compatible_mp4(chosen, job_id)
        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))

    for path in files:
        if path != chosen:
            try:
                os.remove(path)
            except OSError:
                pass

    return chosen, safe_filename(title, chosen)
