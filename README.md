# 📼 DUCKTAPE INDUSTRIAL

> **Zero-Cloud, High-Speed Local LAN & WebRTC P2P File Streaming**  
> *Created & Developed by **Aman Srivastava***

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Netlify Status](https://img.shields.io/badge/Netlify-Ready-00C7B7?logo=netlify&logoColor=white)](https://netlify.com)
[![WebRTC](https://img.shields.io/badge/WebRTC-P2P_Streaming-ff5a1f)](https://webrtc.org)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)](https://python.org)

**DUCKTAPE** is an industrial-grade, zero-cloud local file transfer web application built to stream large files (1GB, 10GB, 50GB+) directly between laptops and mobile devices at raw Wi-Fi speeds (**120MB/s+**). 

No cloud pre-uploads. No storage quotas. No mandatory software downloads. Just scan, pair, and stream.

---

## ⚡ Key Features

* **🌐 Netlify Zero-Download Mode (WebRTC P2P)**: Visitors open your site hosted on Netlify (`https://ducktape.netlify.app`), pick files via standard browser file selector, scan the QR code on their phone, and stream directly browser-to-browser.
* **💻 Python Local LAN Server Mode**: Includes a lightweight Python `aiohttp` server script (`server.py`) that uses native desktop file dialogs to stream files directly off hard drive disk chunks (`8MB`).
* **🔒 100% Air-Gapped & Private**: Transfers happen memory-to-memory over local Wi-Fi or Mobile Hotspots. Data never touches third-party cloud servers.
* **🔓 Unlimited File Sizes**: Transfer 50GB+ movies, 4K ProRes footage, ISOs, or archives without size limits or paywalls.
* **📱 Zero App Installation**: Receiver phones require no apps, APKs, or plugins. Works inside any modern mobile browser.
* **🎨 Industrial Design System**: Powered by `Anton` and `Space Mono` typography, high-contrast industrial yellow accents (`#f4c60e`), dark canvas (`#0D0D0D`), and tactile control states.

---

## 🛠️ Project Architecture

```
ducktape/
├── static/
│   ├── index.html         # Dual-mode (WebRTC P2P + Python Local) Industrial UI
│   └── ducktape_logo.png  # Official DUCKTAPE logo asset
├── server.py              # Python aiohttp streaming server & native file picker
├── start_server.bat       # 1-click Windows launcher (cleans stale port 8080)
├── netlify.toml           # Automated 1-click Netlify deployment configuration
├── requirements.txt       # Python dependencies (aiohttp, qrcode, psutil)
├── LICENSE                # MIT License (Created by Aman Srivastava)
└── README.md              # Documentation & showcase
```

---

## 🚀 Deployment Options

### Option 1: 1-Click Netlify Web Hosting (Zero-Download Web App)

1. Fork or push this repository to your **GitHub** account.
2. Log in to [Netlify.com](https://netlify.com) and click **"Add new site"** ➔ **"Import from GitHub"**.
3. Select your `ducktape` repository.
4. Netlify will automatically detect `netlify.toml` (Publish directory: `static`). Click **Deploy**.

---

### Option 2: Local Python Server Execution

```bash
# Clone the repository
git clone https://github.com/your-username/ducktape.git
cd ducktape

# Install dependencies
pip install -r requirements.txt

# Launch the server (Windows 1-click: double-click start_server.bat)
python server.py
```

* Open `http://localhost:8080` on your laptop.
* Select files via native desktop dialog.
* Scan the QR code on your phone camera!

---

## 📄 License

Created & Maintained by **Aman Srivastava**.  
Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.
