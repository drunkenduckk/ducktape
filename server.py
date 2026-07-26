"""
DUCKTAPE INDUSTRIAL — Full-Stack Render & Local Streaming Engine
Created by Aman Srivastava.

Streams files directly off disk/upload buffer to receiving devices.
Supports Render cloud web hosting + local LAN transfer.
"""

import asyncio
import mimetypes
import os
import shutil
import socket
import time
import uuid
from io import BytesIO

from aiohttp import web
import qrcode

PORT = int(os.environ.get("PORT", 8080))
CHUNK_SIZE = 4 * 1024 * 1024  # 4MB streaming chunks
SESSION_TTL = 7200            # 2 hours session lifetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# In-memory session registry: sid -> {"files": {fid: {"path", "name", "size"}}, "created_at": float}
sessions = {}

routes = web.RouteTableDef()


def prune_stale_memory():
    """Clean up expired session directories and memory entries."""
    now = time.time()
    expired_sids = [sid for sid, info in sessions.items() if now - info.get("created_at", 0) > SESSION_TTL]
    for sid in expired_sids:
        sessions.pop(sid, None)
        sess_dir = os.path.join(UPLOADS_DIR, sid)
        if os.path.exists(sess_dir):
            try:
                shutil.rmtree(sess_dir)
            except Exception:
                pass


@routes.get("/")
async def index(request):
    html_path = os.path.join(STATIC_DIR, "index.html")
    return web.FileResponse(html_path)


@routes.get("/ducktape_logo.png")
async def get_logo(request):
    logo_path = os.path.join(STATIC_DIR, "ducktape_logo.png")
    if not os.path.exists(logo_path):
        logo_path = os.path.join(BASE_DIR, "ducktape_logo.png")
    if os.path.exists(logo_path):
        return web.FileResponse(logo_path)
    return web.Response(status=404, text="logo missing")


@routes.post("/api/upload")
async def upload_files(request):
    prune_stale_memory()
    reader = await request.multipart()
    sid = uuid.uuid4().hex[:10]
    sess_dir = os.path.join(UPLOADS_DIR, sid)
    os.makedirs(sess_dir, exist_ok=True)

    session_files = {}
    file_list = []
    now = time.time()

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            filename = part.filename or "file"
            fid = uuid.uuid4().hex[:8]
            file_path = os.path.join(sess_dir, fid)
            
            size = 0
            with open(file_path, "wb") as f:
                while True:
                    chunk = await part.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)

            session_files[fid] = {
                "path": file_path,
                "name": filename,
                "size": size,
                "created_at": now
            }
            file_list.append({"id": fid, "name": filename, "size": size})

    if not file_list:
        return web.json_response({"error": "No files uploaded"}, status=400)

    sessions[sid] = {"files": session_files, "created_at": now}

    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    url = f"{proto}://{host}/?sid={sid}"

    return web.json_response({"sid": sid, "url": url, "files": file_list})


@routes.get("/api/session/{sid}/files")
async def session_files(request):
    sid = request.match_info["sid"]
    session = sessions.get(sid)
    if not session:
        return web.json_response({"error": "Session expired or not found"}, status=404)

    files = [{"id": fid, "name": f["name"], "size": f["size"]} for fid, f in session["files"].items()]
    return web.json_response({"files": files})


@routes.get("/api/qrcode/{sid}")
async def qrcode_img(request):
    sid = request.match_info["sid"]
    session = sessions.get(sid)
    if not session:
        return web.Response(status=404, text="unknown session")

    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    url = f"{proto}://{host}/?sid={sid}"

    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return web.Response(body=buf.getvalue(), content_type="image/png")


@routes.get("/download/{sid}/{fid}")
async def download(request):
    sid = request.match_info["sid"]
    fid = request.match_info["fid"]
    session = sessions.get(sid)
    if not session or fid not in session["files"]:
        return web.Response(status=404, text="File not found or session expired")

    info = session["files"][fid]
    path, size, name = info["path"], info["size"], info["name"]

    if not os.path.isfile(path):
        return web.Response(status=410, text="Source file no longer on server disk")

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Length": str(size),
            "Content-Type": mimetypes.guess_type(name)[0] or "application/octet-stream",
            "Cache-Control": "no-cache",
        },
    )
    await resp.prepare(request)

    loop = asyncio.get_event_loop()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = await loop.run_in_executor(None, f.read, CHUNK_SIZE)
                if not chunk:
                    break
                await resp.write(chunk)
        await resp.write_eof()
    except (ConnectionResetError, ConnectionError, asyncio.CancelledError, OSError):
        pass
    return resp


def main():
    app = web.Application(client_max_size=1024 * 1024 * 1024 * 50)
    app.add_routes(routes)
    print(f"DUCKTAPE Server running on http://0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
