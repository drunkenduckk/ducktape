"""
DUCKTAPE INDUSTRIAL — WebRTC & WebSocket Stream Hub for Render
Created by Aman Srivastava.

Hosts static web frontend + high-speed WebRTC/WebSocket streaming hub.
Zero file uploads touch server disk. All files stream directly P2P
between devices in real-time.
"""

import asyncio
import os
from aiohttp import web

PORT = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Registry for WebSocket stream channels: sid -> {"sender": ws, "receiver": ws}
channels = {}

routes = web.RouteTableDef()


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


@routes.get("/ws/{sid}/{role}")
async def ws_signal(request):
    sid = request.match_info["sid"]
    role = request.match_info["role"]  # "sender" or "receiver"

    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=16*1024*1024)
    await ws.prepare(request)

    if sid not in channels:
        channels[sid] = {}
    channels[sid][role] = ws

    other_role = "receiver" if role == "sender" else "sender"
    other_ws = channels[sid].get(other_role)

    # Broadcast peer_joined notification to both sides
    if other_ws and not other_ws.closed:
        try:
            await other_ws.send_json({"type": "peer_joined", "role": role})
            await ws.send_json({"type": "peer_joined", "role": other_role})
        except Exception:
            pass

    try:
        async for msg in ws:
            target_ws = channels.get(sid, {}).get(other_role)
            if target_ws and not target_ws.closed:
                if msg.type == web.WSMsgType.TEXT:
                    await target_ws.send_str(msg.data)
                elif msg.type == web.WSMsgType.BINARY:
                    await target_ws.send_bytes(msg.data)
    finally:
        if sid in channels:
            channels[sid].pop(role, None)
            if not channels[sid]:
                channels.pop(sid, None)

    return ws


def main():
    app = web.Application(client_max_size=1024 * 1024 * 1024 * 50)
    app.add_routes(routes)
    print(f"DUCKTAPE Stream Hub running on port {PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
