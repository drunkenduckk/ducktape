"""
Zero-cloud LAN file transfer — laptop -> phone.

Design note (read before touching this):
Browser <input type="file"> cannot yield a real filesystem path (sandboxed
Blob only). To satisfy "stream directly from disk, no pre-upload / no
duplication", file selection happens SERVER-SIDE via a native OS dialog
(tkinter). The browser page only ever sees {id, name, size} — never a path.
Every download reads the real path fresh, in chunks, straight off disk.
"""

import asyncio
import mimetypes
import os
import socket
import time
import uuid
from io import BytesIO

from aiohttp import web

import qrcode

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB raw binary chunks, no encoding for maximum throughput
PORT = 8080
SESSION_TTL = 3600      # 1 hour session lifetime
FILE_CACHE_TTL = 1800   # 30 minutes file pick cache lifetime

# ---- In-memory state. Single-user local tool -> no DB, no persistence. ----
selected_files_cache = {}   # fid -> {"path", "name", "size", "created_at"}
sessions = {}               # sid -> {"files": {fid:{...}}, "ip":str, "port":int, "phone_connected": bool, "created_at"}
sender_sockets = {}         # sid -> WebSocketResponse (laptop tab)
receiver_sockets = {}       # sid -> WebSocketResponse (phone tab)

routes = web.RouteTableDef()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def prune_stale_memory():
    """Purge expired file entries and sessions from memory to prevent memory leaks."""
    now = time.time()
    expired_fids = [fid for fid, info in selected_files_cache.items() if now - info.get("created_at", 0) > FILE_CACHE_TTL]
    for fid in expired_fids:
        selected_files_cache.pop(fid, None)

    expired_sids = [sid for sid, info in sessions.items() if now - info.get("created_at", 0) > SESSION_TTL]
    for sid in expired_sids:
        sessions.pop(sid, None)
        sender_sockets.pop(sid, None)
        receiver_sockets.pop(sid, None)


def _pick_files_native():
    """Blocking native file dialog. Runs in subprocess so Tkinter/PowerShell is on main thread and forced to front."""
    import sys
    import subprocess
    import json

    # Method 1: Tkinter (standalone top-most dialog without parent=root bug)
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

    # Method 2: PowerShell System.Windows.Forms.OpenFileDialog fallback
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
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ducktape_logo.png")
    return web.FileResponse(logo_path)


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
    """Detect real non-loopback, non-APIPA network interfaces."""
    valid = []
    try:
        import psutil
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if not ip.startswith("127.") and not ip.startswith("169.254."):
                        # Prioritize Wi-Fi / Hotspot names
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

    # Sort Wi-Fi adapters first
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
    sessions[sid] = {"files": files, "ip": ip, "port": PORT, "phone_connected": False, "created_at": time.time()}
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
    return web.json_response({"files": files, "phone_connected": session["phone_connected"]})


@routes.post("/api/session/{sid}/start-transfer")
async def start_transfer(request):
    """Laptop clicked the green 'Start Transfer Now' button -> tell the phone to go."""
    sid = request.match_info["sid"]
    session = sessions.get(sid)
    if not session:
        return web.json_response({"error": "unknown session"}, status=404)
    ws = receiver_sockets.get(sid)
    if ws is not None and not ws.closed:
        await ws.send_json({"event": "start_transfer"})
        return web.json_response({"relayed": True})
    return web.json_response({"relayed": False, "note": "phone not connected yet"})


@routes.get("/download/{sid}/{fid}")
async def download(request):
    sid = request.match_info["sid"]
    fid = request.match_info["fid"]
    session = sessions.get(sid)
    if not session or fid not in session["files"]:
        return web.Response(status=404, text="file not found")

    info = session["files"][fid]
    path, size, name = info["path"], info["size"], info["name"]

    if not os.path.isfile(path):
        return web.Response(status=410, text="source file no longer on disk")

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

    # Maximize socket buffer size and disable Nagle's delay algorithm for max throughput
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


@routes.get("/ws/sender/{sid}")
async def ws_sender(request):
    sid = request.match_info["sid"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    sender_sockets[sid] = ws
    try:
        async for _msg in ws:
            pass  # sender tab only listens for phone_connected pushes
    finally:
        sender_sockets.pop(sid, None)
    return ws


@routes.get("/ws/receiver/{sid}")
async def ws_receiver(request):
    sid = request.match_info["sid"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    receiver_sockets[sid] = ws

    session = sessions.get(sid)
    if session is not None:
        session["phone_connected"] = True
        sender_ws = sender_sockets.get(sid)
        if sender_ws is not None and not sender_ws.closed:
            await sender_ws.send_json({"event": "phone_connected"})

    try:
        async for _msg in ws:
            pass
    finally:
        receiver_sockets.pop(sid, None)
        if session is not None:
            session["phone_connected"] = False
    return ws


def main():
    # Allow uploads up to 50 GB over LAN without HTTP 413 Payload Too Large error
    app = web.Application(client_max_size=1024 * 1024 * 1024 * 50)
    app.add_routes(routes)
    print(f"LAN Transfer server running on http://0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
