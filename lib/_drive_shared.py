import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path

import imageio_ffmpeg


GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "") or (
    "http://127.0.0.1:4173/api/drive" if os.environ.get("RAKASHII_DESKTOP") else ""
)
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
FFMPEG_PROCESS_OPTIONS = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if os.name == "nt" else {}
)
TEMP_DIR = tempfile.gettempdir()
TRIM_CACHE_DIR = os.environ.get("RAKASHII_TRIM_CACHE_DIR") or os.path.join(TEMP_DIR, "rakashii-trim-cache")
TRIM_CACHE_TTL_SECONDS = min(
    2 * 60 * 60,
    max(60 * 60, int(os.environ.get("RAKASHII_TRIM_CACHE_TTL_SECONDS", 2 * 60 * 60))),
)
SOURCE_CACHE_DIR = os.environ.get("RAKASHII_SOURCE_CACHE_DIR", "")
SOURCE_CACHE_TTL_SECONDS = min(
    24 * 60 * 60,
    max(60 * 60, int(os.environ.get("RAKASHII_SOURCE_CACHE_TTL_SECONDS", 6 * 60 * 60))),
)
SOURCE_CACHE_LIMIT_BYTES = min(
    3 * 1024 * 1024 * 1024,
    max(512 * 1024 * 1024, int(os.environ.get("RAKASHII_SOURCE_CACHE_LIMIT_BYTES", 3 * 1024 * 1024 * 1024))),
)
os.makedirs(TRIM_CACHE_DIR, exist_ok=True)
if SOURCE_CACHE_DIR:
    os.makedirs(SOURCE_CACHE_DIR, exist_ok=True)
_TRIM_CACHE_LOCKS = {}
_TRIM_CACHE_LOCKS_GUARD = threading.Lock()
_DESKTOP_AUTH_STATES = {}
_DESKTOP_AUTH_TOKENS = {}
_DESKTOP_AUTH_LOCK = threading.Lock()
DESKTOP_AUTH_TTL_SECONDS = 10 * 60
_VIDEO_ENCODER_CANDIDATES = None
_SELECTED_VIDEO_ENCODER = None


def trim_cache_key(file_id, resource_key, public, start, end, filename, quality):
    """Build a stable key for a temporary rendered clip."""
    value = json.dumps([
        str(file_id),
        str(resource_key or ""),
        bool(public),
        round(float(start), 3),
        round(float(end), 3),
        str(filename or ""),
        str(quality or "original").lower(),
    ], separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _trim_cache_path(cache_key):
    return os.path.join(TRIM_CACHE_DIR, f"{cache_key}.mp4")


def is_trim_cache_path(path):
    """Return whether a path belongs to the temporary rendered-clip cache."""
    if not path:
        return False
    try:
        return os.path.commonpath([
            os.path.abspath(path), os.path.abspath(TRIM_CACHE_DIR)
        ]) == os.path.abspath(TRIM_CACHE_DIR)
    except ValueError:
        return False


def _cleanup_trim_cache(now=None):
    now = now or time.time()
    try:
        entries = os.scandir(TRIM_CACHE_DIR)
    except OSError:
        return
    with entries:
        for entry in entries:
            if not entry.name.endswith(".mp4"):
                continue
            try:
                if now - entry.stat().st_mtime > TRIM_CACHE_TTL_SECONDS:
                    os.remove(entry.path)
            except OSError:
                pass


def _trim_cache_lock(cache_key):
    with _TRIM_CACHE_LOCKS_GUARD:
        return _TRIM_CACHE_LOCKS.setdefault(cache_key, threading.Lock())


def _cached_trim_path(cache_key):
    path = _trim_cache_path(cache_key)
    try:
        if time.time() - os.path.getmtime(path) <= TRIM_CACHE_TTL_SECONDS and os.path.getsize(path) > 1024:
            return path
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return None


def _cache_trim_file(source_path, cache_key):
    cached_path = _trim_cache_path(cache_key)
    temporary_path = f"{cached_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(source_path, "rb") as source, open(temporary_path, "wb") as cached:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                cached.write(chunk)
        os.replace(temporary_path, cached_path)
        return cached_path
    finally:
        try:
            os.remove(temporary_path)
        except OSError:
            pass


def source_cache_key(file_id, resource_key, public, filename):
    value = json.dumps([
        str(file_id), str(resource_key or ""), bool(public), str(filename or ""),
    ], separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_cache_path(cache_key):
    return os.path.join(SOURCE_CACHE_DIR, f"{cache_key}.source") if SOURCE_CACHE_DIR else ""


def is_source_cache_path(path):
    if not SOURCE_CACHE_DIR or not path:
        return False
    try:
        return os.path.commonpath([
            os.path.abspath(path), os.path.abspath(SOURCE_CACHE_DIR)
        ]) == os.path.abspath(SOURCE_CACHE_DIR)
    except ValueError:
        return False


def _cleanup_source_cache(now=None):
    if not SOURCE_CACHE_DIR:
        return
    now = now or time.time()
    entries = []
    try:
        with os.scandir(SOURCE_CACHE_DIR) as items:
            for entry in items:
                if not entry.name.endswith(".source"):
                    continue
                try:
                    stat = entry.stat()
                    if now - stat.st_mtime > SOURCE_CACHE_TTL_SECONDS:
                        os.remove(entry.path)
                    else:
                        entries.append((entry.path, stat.st_mtime, stat.st_size))
                except OSError:
                    pass
    except OSError:
        return
    total = sum(size for _, _, size in entries)
    for path, _, size in sorted(entries, key=lambda item: item[1]):
        if total <= SOURCE_CACHE_LIMIT_BYTES:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


def _cached_source_path(cache_key):
    path = _source_cache_path(cache_key)
    if not path:
        return None
    try:
        if time.time() - os.path.getmtime(path) <= SOURCE_CACHE_TTL_SECONDS and os.path.getsize(path) > 1024:
            os.utime(path, None)
            return path
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return None


def cached_source_path(file_id, resource_key, public, filename):
    """Return a reusable local source path, if one is still available."""
    if not SOURCE_CACHE_DIR:
        return None
    _cleanup_source_cache()
    return _cached_source_path(source_cache_key(file_id, resource_key, public, filename))


def _cache_source_file(file_id, token, resource_key, public, filename, progress_callback):
    if not SOURCE_CACHE_DIR:
        return None
    _cleanup_source_cache()
    cache_key = source_cache_key(file_id, resource_key, public, filename)
    cached_path = _cached_source_path(cache_key)
    if cached_path:
        if progress_callback:
            size = os.path.getsize(cached_path)
            progress_callback(size, size)
        return cached_path
    with _trim_cache_lock(f"source:{cache_key}"):
        cached_path = _cached_source_path(cache_key)
        if cached_path:
            return cached_path
        destination = _source_cache_path(cache_key)
        temporary_path = f"{destination}.{os.getpid()}.{threading.get_ident()}.tmp"
        response = None
        try:
            response = source_response(file_id, token, None, resource_key, public)
            total = int(response.headers.get("Content-Length", "0") or 0)
            loaded = 0
            with open(temporary_path, "wb") as output:
                if progress_callback:
                    progress_callback(loaded, total)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    loaded += len(chunk)
                    if progress_callback:
                        progress_callback(loaded, total)
            if loaded <= 1024:
                raise RuntimeError("The downloaded Drive source was empty.")
            os.replace(temporary_path, destination)
            _cleanup_source_cache()
            return destination
        finally:
            if response:
                response.close()
            try:
                os.remove(temporary_path)
            except OSError:
                pass


def json_body(handler):
    length = int(handler.headers.get("content-length", "0") or 0)
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")


def send_json(handler, payload, status=200, extra_headers=None):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    for key, value in (extra_headers or {}).items():
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def cookie_value(handler, name):
    cookie = SimpleCookie()
    cookie.load(handler.headers.get("Cookie", ""))
    morsel = cookie.get(name)
    return morsel.value if morsel else ""


def encode_token(token):
    raw = json.dumps(token, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_token(value):
    try:
        padded = value + "=" * (-len(value) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def cookie_flags(handler):
    forwarded = handler.headers.get("X-Forwarded-Proto", "")
    secure = "; Secure" if forwarded == "https" or os.environ.get("VERCEL") else ""
    return f"Path=/; HttpOnly; SameSite=Lax{secure}"


def token_from_request(handler):
    token = decode_token(cookie_value(handler, "rakashii_drive_token"))
    if token.get("access_token"):
        return token
    return None


def register_desktop_auth_state(state, handoff):
    now = time.time()
    with _DESKTOP_AUTH_LOCK:
        _DESKTOP_AUTH_STATES.clear()
        _DESKTOP_AUTH_TOKENS.clear()
        _DESKTOP_AUTH_STATES[state] = (handoff, now + DESKTOP_AUTH_TTL_SECONDS)


def take_desktop_auth_handoff(state):
    now = time.time()
    with _DESKTOP_AUTH_LOCK:
        value = _DESKTOP_AUTH_STATES.pop(state, None)
    if not value or value[1] < now:
        return ""
    return value[0]


def store_desktop_auth_token(handoff, token):
    with _DESKTOP_AUTH_LOCK:
        _DESKTOP_AUTH_TOKENS[handoff] = (token, time.time() + DESKTOP_AUTH_TTL_SECONDS)


def take_desktop_auth_token(handoff):
    now = time.time()
    with _DESKTOP_AUTH_LOCK:
        value = _DESKTOP_AUTH_TOKENS.pop(handoff, None)
    if not value or value[1] < now:
        return None
    return value[0]


def oauth_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def oauth_missing():
    values = {
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "GOOGLE_REDIRECT_URI": GOOGLE_REDIRECT_URI,
    }
    return [name for name, value in values.items() if not value]


def auth_redirect(handler):
    if not oauth_configured():
        send_json(handler, {"error": "Google OAuth is not configured for this installation."}, 500)
        return
    state = secrets.token_urlsafe(24)
    handoff = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query).get("handoff", [""])[0]
    if handoff:
        register_desktop_auth_state(state, handoff)
    params = urllib.parse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "select_account" if handoff else "consent",
        "scope": GOOGLE_SCOPE,
        "state": state,
    })
    handler.send_response(302)
    handler.send_header("Location", f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
    handler.send_header("Set-Cookie", f"rakashii_drive_state={state}; {cookie_flags(handler)}; Max-Age=600")
    handler.end_headers()


def exchange_code(code):
    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.loads(response.read().decode("utf-8"))
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    return token


def drive_api(path, token, params=None, method="GET", body=None, headers=None):
    query = urllib.parse.urlencode(params or {})
    url = f"https://www.googleapis.com/drive/v3/{path.lstrip('/')}"
    if query:
        url += f"?{query}"
    request_headers = {"Authorization": f"Bearer {token}"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        return urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            message = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            message = detail or error.reason
        raise RuntimeError(message) from error


def drive_json(path, token, params=None):
    with drive_api(path, token, params=params) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_drive_link(value):
    text = str(value or "").strip()
    match = re.search(r"/file/d/([A-Za-z0-9_-]+)", text) or re.search(r"[?&]id=([A-Za-z0-9_-]+)", text)
    file_id = match.group(1) if match else (text if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text) else "")
    resource_key = ""
    try:
        resource_key = urllib.parse.parse_qs(urllib.parse.urlparse(text).query).get("resourcekey", [""])[0]
    except Exception:
        pass
    return file_id, resource_key


def public_headers(file_id, resource_key=""):
    return {"X-Goog-Drive-Resource-Keys": f"{file_id}/{resource_key}"} if resource_key else {}


def public_drive_response(file_id, range_header=None, resource_key=""):
    resource = f"&resourcekey={urllib.parse.quote(resource_key)}" if resource_key else ""
    urls = [
        f"https://drive.usercontent.google.com/download?id={urllib.parse.quote(file_id)}&export=download&confirm=t{resource}",
        f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(file_id)}{resource}",
    ]
    last_error = None
    for url in urls:
        headers = public_headers(file_id, resource_key)
        if range_header:
            headers["Range"] = range_header
        try:
            response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90)
            content_type = response.headers.get("Content-Type", "")
            if not content_type.lower().startswith("text/html"):
                return response
            html = response.read(1024 * 1024).decode("utf-8", "replace")
            token = re.search(r'name=["\']confirm["\']\s+value=["\']([^"\']+)', html, re.I)
            if not token:
                token = re.search(r"[?&]confirm=([A-Za-z0-9_-]+)", html, re.I)
            if token:
                confirmed = urllib.request.urlopen(
                    urllib.request.Request(
                        f"{url}&confirm={urllib.parse.quote(token.group(1))}",
                        headers={**headers, "Cookie": "; ".join(f"{k}={v}" for k, v in response.headers.items() if k.lower() == "set-cookie")},
                    ),
                    timeout=90,
                )
                if not confirmed.headers.get("Content-Type", "").lower().startswith("text/html"):
                    return confirmed
            last_error = RuntimeError("The Drive file is not publicly downloadable.")
        except Exception as error:
            last_error = error
    raise last_error or RuntimeError("Could not open the public Drive link.")


def filename_from_headers(headers, fallback):
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I) or re.search(r'filename="?([^";]+)', disposition, re.I)
    name = urllib.parse.unquote(match.group(1)) if match else fallback
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def video_mime(filename, hint=""):
    declared = str(hint or "").split(";", 1)[0].strip().lower()
    return declared if declared.startswith("video/") else mimetypes.guess_type(filename)[0] or "video/mp4"


def stream_upstream(handler, response, fallback_name="drive-video.mp4", mime_hint=""):
    content_range = response.headers.get("Content-Range")
    partial = response.status == 206 and bool(content_range)
    filename = filename_from_headers(response.headers, fallback_name)
    handler.send_response(206 if partial else 200)
    handler.send_header("Content-Type", video_mime(filename, mime_hint))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "private, max-age=300")
    handler.send_header("Content-Disposition", f'inline; filename="{filename}"')
    if content_range and partial:
        handler.send_header("Content-Range", content_range)
    if response.headers.get("Content-Length"):
        handler.send_header("Content-Length", response.headers["Content-Length"])
    handler.end_headers()
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        handler.wfile.write(chunk)


def source_response(file_id, token=None, range_header=None, resource_key="", public=False):
    if public:
        return public_drive_response(file_id, range_header, resource_key)
    headers = {"Range": range_header} if range_header else {}
    params = {"alt": "media", "supportsAllDrives": "true", "acknowledgeAbuse": "true"}
    if resource_key:
        params["resourceKey"] = resource_key
    query = urllib.parse.urlencode(params)
    return urllib.request.urlopen(urllib.request.Request(
        f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id)}?{query}",
        headers={"Authorization": f"Bearer {token}", **headers},
    ), timeout=90)


def metadata(file_id, token, resource_key=""):
    params = {"fields": "id,name,size,mimeType,resourceKey,thumbnailLink"}
    if resource_key:
        params["resourceKey"] = resource_key
    return drive_json(f"files/{urllib.parse.quote(file_id)}", token, params)


def thumbnail_response(file_id, token, resource_key=""):
    file = metadata(file_id, token, resource_key)
    thumbnail_url = file.get("thumbnailLink")
    if not thumbnail_url:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    headers.update(public_headers(file_id, resource_key))
    return urllib.request.urlopen(urllib.request.Request(thumbnail_url, headers=headers), timeout=30)


def video_encoder_candidates():
    """Prefer hardware encoders, but always retain a CPU fallback."""
    global _VIDEO_ENCODER_CANDIDATES
    if _VIDEO_ENCODER_CANDIDATES is not None:
        return _VIDEO_ENCODER_CANDIDATES
    if os.environ.get("RAKASHII_DISABLE_GPU", "").lower() in {"1", "true", "yes"}:
        _VIDEO_ENCODER_CANDIDATES = ["libx264"]
        return _VIDEO_ENCODER_CANDIDATES

    try:
        encoder_list = subprocess.run(
            [FFMPEG_LOCATION, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
            **FFMPEG_PROCESS_OPTIONS,
        ).stdout
    except Exception:
        encoder_list = ""

    configured = os.environ.get("RAKASHII_VIDEO_ENCODER", "").strip()
    hardware = [name for name in (configured, "h264_nvenc", "h264_qsv", "h264_amf") if name]
    _VIDEO_ENCODER_CANDIDATES = [name for name in hardware if name in encoder_list]
    _VIDEO_ENCODER_CANDIDATES.append("libx264")
    return _VIDEO_ENCODER_CANDIDATES


def selected_video_encoder():
    """Probe hardware locally so Drive is not streamed once per failed encoder."""
    global _SELECTED_VIDEO_ENCODER
    if _SELECTED_VIDEO_ENCODER:
        return _SELECTED_VIDEO_ENCODER
    for encoder in video_encoder_candidates():
        if encoder == "libx264":
            _SELECTED_VIDEO_ENCODER = encoder
            break
        try:
            probe = subprocess.run(
                [
                    FFMPEG_LOCATION, "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=size=16x16:rate=1",
                    "-frames:v", "1", "-c:v", encoder, "-f", "null", "-",
                ],
                capture_output=True,
                timeout=15,
                **FFMPEG_PROCESS_OPTIONS,
            )
            if probe.returncode == 0:
                _SELECTED_VIDEO_ENCODER = encoder
                break
        except Exception:
            continue
    _SELECTED_VIDEO_ENCODER = _SELECTED_VIDEO_ENCODER or "libx264"
    return _SELECTED_VIDEO_ENCODER


def clip_source(file_id, token, resource_key, public, start, end, filename, quality="original", progress_callback=None):
    _cleanup_trim_cache()
    cache_key = trim_cache_key(file_id, resource_key, public, start, end, filename, quality)
    with _trim_cache_lock(cache_key):
        cached_path = _cached_trim_path(cache_key)
        if cached_path:
            if progress_callback:
                progress_callback(1, 1)
            return cached_path
        return _clip_source_uncached(
            file_id, token, resource_key, public, start, end, filename, quality,
            progress_callback, cache_key,
        )


def _clip_source_uncached(file_id, token, resource_key, public, start, end, filename, quality, progress_callback, cache_key):
    suffix = Path(filename).suffix or ".mp4"
    input_path = tempfile.mktemp(prefix="drive-clip-", suffix=suffix, dir=TEMP_DIR)
    fast_output_path = tempfile.mktemp(prefix="drive-clip-fast-", suffix=".mp4", dir=TEMP_DIR)
    output_path = tempfile.mktemp(prefix="drive-clip-out-", suffix=".mp4", dir=TEMP_DIR)
    result_path = None
    duration = max(0.1, float(end) - float(start))
    try:
        source_cached_path = _cache_source_file(
            file_id, token, resource_key, public, filename, progress_callback
        )
    except Exception:
        # Preserve the streaming fallback if the optional source cache cannot
        # be written because of disk space or a transient filesystem error.
        source_cached_path = None

    def cached_result(path):
        nonlocal result_path
        result_path = _cache_trim_file(path, cache_key)
        return result_path

    def command_for(input_name, destination, copy_video, stream_input=False, video_encoder="libx264"):
        command = [FFMPEG_LOCATION, "-y", "-hide_banner", "-loglevel", "error"]
        if not stream_input:
            command += ["-ss", str(start)]
        command += ["-i", input_name]
        if stream_input:
            command += ["-ss", str(start)]
        command += ["-t", str(duration), "-map", "0:v:0", "-map", "0:a:0?"]
        if copy_video:
            command += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            crf = {"high": "16", "balanced": "23", "smaller": "28"}.get(quality, "14")
            audio_bitrate = {"high": "256k", "balanced": "160k", "smaller": "128k"}.get(quality, "256k")
            if video_encoder == "h264_nvenc":
                video_args = ["-c:v", video_encoder, "-preset", "p4", "-cq", crf]
            elif video_encoder == "h264_qsv":
                video_args = ["-c:v", video_encoder, "-global_quality", crf]
            elif video_encoder == "h264_amf":
                video_args = ["-c:v", video_encoder, "-quality", "quality", "-qp_i", crf, "-qp_p", crf]
            else:
                preset = "veryfast"
                video_args = ["-c:v", "libx264", "-preset", preset, "-crf", crf]
            command += video_args + [
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", audio_bitrate,
                "-ar", "48000",
            ]
        command += ["-movflags", "+faststart", destination]
        return command

    def stream_into_ffmpeg(copy_video, video_encoder="libx264"):
        destination = fast_output_path if copy_video else output_path
        response = None
        process = None
        feeder = None
        try:
            response = source_response(file_id, token, None, resource_key, public)
            total = int(response.headers.get("Content-Length", "0") or 0)
            process = subprocess.Popen(
                command_for("pipe:0", destination, copy_video, stream_input=True, video_encoder=video_encoder),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **FFMPEG_PROCESS_OPTIONS,
            )

            def feed_source():
                loaded = 0
                try:
                    if progress_callback:
                        progress_callback(loaded, total)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        try:
                            process.stdin.write(chunk)
                        except (BrokenPipeError, OSError):
                            break
                        loaded += len(chunk)
                        if progress_callback:
                            progress_callback(loaded, total)
                finally:
                    try:
                        process.stdin.close()
                    except (BrokenPipeError, OSError, AttributeError):
                        pass

            feeder = threading.Thread(target=feed_source, daemon=True)
            feeder.start()
            return_code = process.wait(timeout=300)
            feeder.join(timeout=10)
            if return_code == 0 and os.path.exists(destination) and os.path.getsize(destination) > 1024:
                return destination
        except Exception:
            if process and process.poll() is None:
                process.kill()
                process.wait()
        finally:
            if response:
                response.close()
            if process and process.poll() is None:
                process.kill()
                process.wait()
            if feeder and feeder.is_alive():
                feeder.join(timeout=1)
            if os.path.exists(destination) and (not process or process.returncode != 0):
                try:
                    os.remove(destination)
                except OSError:
                    pass
        return None

    try:
        # Desktop mode stores the source once so later clips from the same
        # Drive file do not download the entire source again. Other modes keep
        # the streaming path for lower temporary-disk usage.
        if not source_cached_path:
            if quality == "original":
                result_path = stream_into_ffmpeg(copy_video=True)
                if result_path:
                    return cached_result(result_path)
            encoders = [selected_video_encoder()]
            if encoders[0] != "libx264":
                encoders.append("libx264")
            for video_encoder in encoders:
                result_path = stream_into_ffmpeg(copy_video=False, video_encoder=video_encoder)
                if result_path:
                    return cached_result(result_path)

        # Some Drive formats do not demux reliably from a pipe. Keep the older
        # full-download path as a compatibility fallback for those files.
        if source_cached_path:
            input_path = source_cached_path
        else:
            response = source_response(file_id, token, None, resource_key, public)
            try:
                with open(input_path, "wb") as output:
                    loaded = 0
                    total = int(response.headers.get("Content-Length", "0") or 0)
                    if progress_callback:
                        progress_callback(loaded, total)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        loaded += len(chunk)
                        if progress_callback:
                            progress_callback(loaded, total)
            finally:
                response.close()

        if quality == "original":
            fast_result = subprocess.run(
                command_for(input_path, fast_output_path, True),
                capture_output=True,
                text=True,
                timeout=300,
                **FFMPEG_PROCESS_OPTIONS,
            )
            if fast_result.returncode == 0 and os.path.exists(fast_output_path) and os.path.getsize(fast_output_path) > 1024:
                result_path = fast_output_path
                return cached_result(result_path)

        last_error = "FFmpeg failed"
        encoders = [selected_video_encoder()]
        if encoders[0] != "libx264":
            encoders.append("libx264")
        for video_encoder in encoders:
            result = subprocess.run(
                command_for(input_path, output_path, False, video_encoder=video_encoder),
                capture_output=True,
                text=True,
                timeout=300,
                **FFMPEG_PROCESS_OPTIONS,
            )
            if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                result_path = output_path
                return cached_result(result_path)
            if result.stderr.strip():
                last_error = result.stderr.strip().splitlines()[-1]
        raise RuntimeError(last_error)
    finally:
        for path in (input_path, fast_output_path, output_path):
            if path and path != result_path and not is_source_cache_path(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
