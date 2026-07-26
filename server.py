"""
DUCKTAPE INDUSTRIAL — Zero-Cloud High-Speed LAN Streaming Engine
Created by Aman Srivastava.

Zero-cloud local file transfer: laptop -> phone over Wi-Fi / Mobile Hotspot.
No files are EVER uploaded to any server. Every download reads the original
file fresh, in binary chunks, straight off the local disk.
"""

import asyncio
import json
import mimetypes
import os
import socket
import subprocess
import sys
import time
import uuid
from io import BytesIO

from aiohttp import web
import qrcode

PORT = 8080
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB raw binary streaming chunks
SESSION_TTL = 3600            # 1 hour session lifetime
FILE_CACHE_TTL = 1800         # 30 mins file pick cache lifetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# In-memory file cache: fid -> {"path", "name", "size", "created_at"}
selected_files_cache = {}

# In-memory session registry: sid -> {"files": {fid: info}, "ip": str, "port": int, "created_at": float}
sessions = {}

routes = web.RouteTableDef()


def prune_stale_memory():
    """Purge expired file entries and sessions from memory."""
    now = time.time()
    expired_fids = [fid for fid, info in selected_files_cache.items() if now - info.get("created_at", 0) > FILE_CACHE_TTL]
    for fid in expired_fids:
        selected_files_cache.pop(fid, None)

    expired_sids = [sid for sid, info in sessions.items() if now - info.get("created_at", 0) > SESSION_TTL]
    for sid in expired_sids:
        sessions.pop(sid, None)


def _pick_files_native():
    """Blocking native file dialog via Tkinter/PowerShell. Returns list of file paths."""
    # Method 1: Tkinter standalone top-most dialog
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "import json\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        "paths = filedialog.askopenfilenames(title='Select files to share')\n"
        "root.destroy()\n"
        "print(json.dumps(list(paths)))\n"
    )
    try:
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120
        )
        if res.returncode == 0 and res.stdout.strip():
            out = json.loads(res.stdout.strip())
            if out:
                return out
    except Exception as e:
        print(f"Tkinter file picker failed: {e}")

    # Method 2: PowerShell System.Windows.Forms dialog fallback
    ps_cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$f = New-Object System.Windows.Forms.OpenFileDialog; "
        "$f.Multiselect = $true; "
        "$f.Title = 'Select files to share'; "
        "$res = $f.ShowDialog(); "
        "if ($res -eq [System.Windows.Forms.DialogResult]::OK) { "
        "  ConvertTo-Json -InputObject @($f.FileNames) -Compress "
        "} else { '[]' }"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=120
        )
        if res.returncode == 0 and res.stdout.strip():
            raw = res.stdout.strip()
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                return [parsed]
            elif isinstance(parsed, list):
                return parsed
    except Exception as e:
        print(f"PowerShell file picker failed: {e}")

    return []


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


@routes.post("/api/select-files")
async def select_files(request):
    prune_stale_memory()
    loop = asyncio.get_event_loop()
    try:
        paths = await loop.run_in_executor(None, _pick_files_native)
    except Exception as e:
        return web.json_response({"error": f"native dialog failed: {e}"}, status=500)

    result = []
    now = time.time()
    for p in paths:
        if not os.path.isfile(p):
            continue
        fid = uuid.uuid4().hex[:8]
        entry = {"path": p, "name": os.path.basename(p), "size": os.path.getsize(p), "created_at": now}
        selected_files_cache[fid] = entry
        result.append({"id": fid, "name": entry["name"], "size": entry["size"]})
    return web.json_response({"files": result})


def get_valid_network_interfaces():
    """Detect real non-loopback network interfaces (Wi-Fi / Mobile Hotspot)."""
    valid = []
    try:
        import psutil
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if not ip.startswith("127.") and not ip.startswith("169.254."):
                        is_wifi = any(w in name.lower() for w in ["wi-fi", "wifi", "wireless", "hotspot", "wlan"])
                        valid.append({"name": name, "ip": ip, "is_wifi": is_wifi})
    except Exception:
        pass

    if not valid:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                valid.append({"name": "Wi-Fi Default", "ip": ip, "is_wifi": True})
        except Exception:
            pass
        finally:
            s.close()

    if not valid:
        valid.append({"name": "Localhost", "ip": "127.0.0.1", "is_wifi": False})

    valid.sort(key=lambda x: 0 if x["is_wifi"] else 1)
    return valid


@routes.get("/api/network-interfaces")
async def network_interfaces(request):
    interfaces = get_valid_network_interfaces()
    primary_ip = interfaces[0]["ip"] if interfaces else "127.0.0.1"
    return web.json_response({
        "ip": primary_ip,
        "interfaces": [{"name": i["name"], "ip": i["ip"]} for i in interfaces]
    })


@routes.post("/api/create-session")
async def create_session(request):
    prune_stale_memory()
    body = await request.json()
    ip = body.get("ip")
    file_ids = body.get("file_ids", [])
    if not ip or not file_ids:
        return web.json_response({"error": "ip and file_ids required"}, status=400)

    sid = uuid.uuid4().hex[:10]
    files = {fid: selected_files_cache[fid] for fid in file_ids if fid in selected_files_cache}
    sessions[sid] = {"files": files, "ip": ip, "port": PORT, "created_at": time.time()}
    url = f"http://{ip}:{PORT}/?sid={sid}"
    return web.json_response({"sid": sid, "url": url})


@routes.get("/api/qrcode/{sid}")
async def qrcode_img(request):
    sid = request.match_info["sid"]
    session = sessions.get(sid)
    if not session:
        return web.Response(status=404, text="unknown session")

    url = f"http://{session['ip']}:{session['port']}/?sid={sid}"
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return web.Response(body=buf.getvalue(), content_type="image/png")


@routes.get("/api/session/{sid}/files")
async def session_files(request):
    sid = request.match_info["sid"]
    session = sessions.get(sid)
    if not session:
        return web.json_response({"error": "unknown session"}, status=404)

    files = [{"id": fid, "name": f["name"], "size": f["size"]} for fid, f in session["files"].items()]
    return web.json_response({"files": files})


@routes.get("/download/{sid}/{fid}")
async def download(request):
    sid = request.match_info["sid"]
    fid = request.match_info["fid"]
    session = sessions.get(sid)
    if not session or fid not in session["files"]:
        return web.Response(status=404, text="File not found")

    info = session["files"][fid]
    path, size, name = info["path"], info["size"], info["name"]

    if not os.path.isfile(path):
        return web.Response(status=410, text="Source file no longer on local disk")

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

    # Maximize socket send buffer & disable Nagle's algorithm for 100+ MB/s Wi-Fi throughput
    try:
        sock = request.transport.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
    except Exception:
        pass

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
    print(f"DUCKTAPE Zero-Cloud LAN Server running on http://0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
