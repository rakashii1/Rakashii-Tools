import os
import sys
from urllib.parse import parse_qs, urlparse

API_DIR = os.path.dirname(__file__)
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from _drive_shared import (
    auth_redirect,
    clip_source,
    cookie_flags,
    cookie_value,
    decode_token,
    drive_json,
    encode_token,
    exchange_code,
    filename_from_headers,
    json_body,
    metadata,
    oauth_configured,
    oauth_missing,
    parse_drive_link,
    public_drive_response,
    send_json,
    store_desktop_auth_token,
    source_response,
    stream_upstream,
    is_trim_cache_path,
    thumbnail_response,
    take_desktop_auth_handoff,
    take_desktop_auth_token,
    token_from_request,
    video_mime,
)


def query(handler):
    return parse_qs(urlparse(handler.path).query)


def parse_time(value):
    parts = str(value or "").strip().split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return None


def handle_callback(handler):
    params = query(handler)
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]
    if not code or not state or state != cookie_value(handler, "rakashii_drive_state"):
        send_json(handler, {"error": "Google authorization state was invalid."}, 400)
        return
    try:
        token = exchange_code(code)
        handoff = take_desktop_auth_handoff(state)
        if handoff:
            store_desktop_auth_token(handoff, token)
        handler.send_response(302)
        handler.send_header("Location", "/google-drive-clipper.html")
        handler.send_header("Set-Cookie", f"rakashii_drive_token={encode_token(token)}; {cookie_flags(handler)}; Max-Age=2592000")
        handler.send_header("Set-Cookie", f"rakashii_drive_state=; {cookie_flags(handler)}; Max-Age=0")
        handler.end_headers()
    except Exception as error:
        send_json(handler, {"error": f"Google authorization failed: {error}"}, 500)


def handle_desktop_auth_poll(handler):
    handoff = query(handler).get("handoff", [""])[0]
    token = take_desktop_auth_token(handoff) if handoff else None
    if not token:
        send_json(handler, {"connected": False}, 202)
        return
    send_json(
        handler,
        {"connected": True},
        extra_headers={
            "Set-Cookie": f"rakashii_drive_token={encode_token(token)}; {cookie_flags(handler)}; Max-Age=2592000",
        },
    )


def handle_files(handler):
    token_data = token_from_request(handler)
    if not token_data:
        send_json(handler, {"error": "Connect Google Drive first."}, 401)
        return
    params = query(handler)
    source = params.get("source", ["my-drive"])[0]
    folder_id = params.get("folderId", ["root"])[0]
    escaped = folder_id.replace("'", "\\'")
    parent = "sharedWithMe = true" if source == "shared" and folder_id == "root" else f"'{escaped}' in parents"
    drive_params = {
        "pageSize": 100,
        "spaces": "drive",
        "corpora": "user",
        "includeItemsFromAllDrives": "true",
        "supportsAllDrives": "true",
        "orderBy": "name",
        "q": f"{parent} and trashed = false",
        "fields": "files(id,name,size,mimeType,modifiedTime,webViewLink,thumbnailLink,resourceKey,permissions(type,role),driveId,shortcutDetails,capabilities/canDownload,parents)",
    }
    try:
        data = drive_json("files", token_data["access_token"], drive_params)
        items = [item for item in data.get("files", []) if item.get("mimeType") == "application/vnd.google-apps.folder" or item.get("mimeType", "").startswith("video/")]
        for item in items:
            item["public"] = any(permission.get("type") == "anyone" and permission.get("role") in {"reader", "commenter", "writer"} for permission in item.get("permissions", []))
        send_json(handler, {"source": source, "folderId": folder_id, "items": items})
    except OSError as error:
        if error.errno == 28:
            send_json(handler, {
                "error": "The video is too large for Vercel's temporary storage. Use a smaller file or configure a separate video-processing server."
            }, 507)
            return
        send_json(handler, {"error": str(error)}, 500)
    except Exception as error:
        send_json(handler, {"error": str(error)}, 500)


def handle_preview(handler, public=False):
    params = query(handler)
    file_id, link_resource_key = parse_drive_link(params.get("fileId", [""])[0])
    resource_key = params.get("resourceKey", [link_resource_key])[0]
    if not file_id:
        handler.send_error(400, "Invalid Google Drive file ID")
        return
    token_data = token_from_request(handler)
    if not public and not token_data:
        handler.send_error(401, "Connect Google Drive first")
        return
    try:
        token = token_data["access_token"] if token_data else None
        range_header = handler.headers.get("Range")
        if public:
            response = public_drive_response(file_id, range_header, resource_key)
            fallback = params.get("fileName", [f"drive-{file_id}.mp4"])[0]
            mime_hint = params.get("mimeType", [""])[0]
        else:
            response = source_response(file_id, token, range_header, resource_key)
            fallback = params.get("fileName", [f"drive-{file_id}.mp4"])[0]
            mime_hint = params.get("mimeType", ["video/mp4"])[0]
        try:
            stream_upstream(handler, response, fallback, mime_hint)
        finally:
            response.close()
    except Exception as error:
        send_json(handler, {"error": str(error)}, 400)


def handle_thumbnail(handler):
    params = query(handler)
    file_id, link_resource_key = parse_drive_link(params.get("fileId", [""])[0])
    resource_key = params.get("resourceKey", [link_resource_key])[0]
    token_data = token_from_request(handler)
    if not file_id or not token_data:
        handler.send_error(401, "Connect Google Drive first")
        return
    response = None
    try:
        response = thumbnail_response(file_id, token_data["access_token"], resource_key)
        if response is None:
            handler.send_error(404, "No thumbnail is available for this video")
            return
        handler.send_response(200)
        handler.send_header("Content-Type", response.headers.get("Content-Type", "image/jpeg"))
        handler.send_header("Cache-Control", "private, max-age=3600")
        if response.headers.get("Content-Length"):
            handler.send_header("Content-Length", response.headers["Content-Length"])
        handler.end_headers()
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            handler.wfile.write(chunk)
    except Exception as error:
        handler.send_error(400, str(error))
    finally:
        if response is not None:
            response.close()


def handle_public_file(handler):
    try:
        file_id, resource_key = parse_drive_link(json_body(handler).get("link"))
        if not file_id:
            send_json(handler, {"error": "Paste a valid Google Drive file link."}, 400)
            return
        response = public_drive_response(file_id, None, resource_key)
        filename = filename_from_headers(response.headers, f"drive-{file_id}.mp4")
        size = int(response.headers.get("Content-Length", "0") or 0)
        mime_type = video_mime(filename, response.headers.get("Content-Type", ""))
        response.close()
        send_json(handler, {"id": file_id, "resourceKey": resource_key, "name": filename, "size": size, "mimeType": mime_type, "public": True})
    except Exception as error:
        send_json(handler, {"error": f"{error} Make sure the file is set to Anyone with the link."}, 400)


def handle_clip(handler):
    data = json_body(handler)
    file_id, link_resource_key = parse_drive_link(data.get("fileId"))
    resource_key = str(data.get("resourceKey") or link_resource_key)
    start = parse_time(data.get("start"))
    end = parse_time(data.get("end"))
    public = bool(data.get("public"))
    quality = str(data.get("quality") or "original").lower()
    if quality not in {"original", "high", "balanced", "smaller"}:
        quality = "original"
    token_data = token_from_request(handler)
    if not file_id or start is None or end is None or start < 0 or end <= start or (not public and not token_data):
        send_json(handler, {"error": "Use a valid video, start time, and end time."}, 400)
        return
    try:
        token = token_data["access_token"] if token_data else None
        filename = f"drive-{file_id}.mp4"
        use_public_source = public and not token_data
        if token:
            filename = metadata(file_id, token, resource_key).get("name", filename)
        output_path = clip_source(file_id, token, resource_key, use_public_source, start, end, filename, quality)
        download_name = f"{os.path.splitext(filename)[0]}-clip.mp4"
        handler.send_response(200)
        handler.send_header("Content-Type", "video/mp4")
        handler.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        handler.send_header("Content-Length", str(os.path.getsize(output_path)))
        handler.end_headers()
        with open(output_path, "rb") as output:
            while True:
                chunk = output.read(1024 * 1024)
                if not chunk:
                    break
                handler.wfile.write(chunk)
        if not is_trim_cache_path(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
    except Exception as error:
        send_json(handler, {"error": str(error)}, 500)


def handle_get(handler, action):
    if action == "auth":
        return auth_redirect(handler)
    if action == "callback":
        return handle_callback(handler)
    if action == "desktop_auth_poll":
        return handle_desktop_auth_poll(handler)
    if action == "logout":
        handler.send_response(302)
        handler.send_header("Location", "/google-drive-clipper.html")
        handler.send_header("Set-Cookie", f"rakashii_drive_token=; {cookie_flags(handler)}; Max-Age=0")
        handler.end_headers()
        return
    if action == "status":
        token_data = token_from_request(handler)
        account = {}
        auth_error = ""
        if token_data:
            try:
                about = drive_json("about", token_data["access_token"], {"fields": "user(displayName,emailAddress,photoLink)"})
                raw_account = about.get("user") or {}
                account = {
                    "displayName": raw_account.get("displayName") or raw_account.get("givenName") or raw_account.get("firstName") or raw_account.get("name") or "",
                    "emailAddress": raw_account.get("emailAddress") or raw_account.get("email") or "",
                    "photoLink": raw_account.get("photoLink") or raw_account.get("picture") or "",
                }
            except Exception as error:
                auth_error = str(error)
        return send_json(handler, {
            "connected": bool(token_data and not auth_error),
            "configured": oauth_configured(),
            "missing": oauth_missing(),
            "user": account,
            "authError": auth_error,
        })
    if action == "files":
        return handle_files(handler)
    if action == "preview":
        return handle_preview(handler, False)
    if action == "public_preview":
        return handle_preview(handler, True)
    if action == "thumbnail":
        return handle_thumbnail(handler)
    send_json(handler, {"error": "Unknown Drive action."}, 404)


def handle_post(handler, action):
    if action == "public_file":
        return handle_public_file(handler)
    if action == "clip":
        return handle_clip(handler)
    send_json(handler, {"error": "Unknown Drive action."}, 404)
