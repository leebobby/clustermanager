# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

**clustermanager** — a cluster configuration, management, and diagnostics system with a
three-plane network architecture (management/GE, control/10GE, data/100GE).

## Stack

- **Backend**: Python, FastAPI, SQLAlchemy (SQLite by default), Uvicorn
- **Frontend**: Vue 3, Vite, Element Plus, Vue Router, Axios, D3.js (topology visualization)

## Running the backend

```bash
cd backend
pip install -r requirements.txt
python run.py
# or: uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

On startup the backend auto-initializes the SQLite DB and seeds demo data
(1 Master + 5 Slave + 1 Sensor node). Swagger docs at http://localhost:8000/docs.

## Running the frontend

```bash
cd frontend
npm install
npm run dev    # dev server on http://localhost:3000
npm run build  # production build
```

## Building the app

`build_app.py` at the repo root is the single build entry point (cross-platform):

```bash
python build_app.py                  # auto: Windows -> desktop, otherwise server
python build_app.py --mode desktop   # pywebview native window (cluster-manager.exe)
python build_app.py --mode server    # uvicorn console process (browser access)
```

It runs `npm run build`, installs deps, runs PyInstaller (`backend/cluster_manager.spec`,
mode selected via the `CLUSTER_MANAGER_BUILD_MODE` env var), copies runtime resources
next to the executable, smoke-tests the result in server mode, and archives it.
`build.bat` / `build.sh` are thin wrappers around it — do not reimplement build steps
in them.

Windows rendering: the desktop build needs Edge WebView2. Win11 has it built in, Win10
usually does not, and pywebview silently falls back to MSHTML (IE11), which renders the
Vue 3 app blank white. `backend/desktop.py::probe_webview2()` decides between a bundled
fixed-version runtime, the system runtime, and a browser fallback (Edge/Chrome
`--app=URL`). Bundle a runtime with `--webview2 PATH` for offline machines. The decision
table is covered by `backend/test_desktop_probe.py` (plain python, no pytest) — run it
after touching that logic, since it cannot be exercised on a dev machine.

## Backend architecture

```
backend/
├── main.py          # FastAPI app entry, DB init, router registration
├── run.py           # Convenience launcher
├── config.py        # Paths / runtime config
├── models/          # SQLAlchemy ORM models
├── api/             # Route handlers: nodes, network, alerts, diagnose, ipmi, patrol, pxe, firmware
└── services/        # Business logic: ipmi_service, network_service, pxe_service, redfish_service,
                     #   diag_service, cred_service
```

## Frontend architecture

```
frontend/src/
├── main.js          # App entry, Element Plus setup
├── App.vue          # Root layout with sidebar navigation
├── router/          # Vue Router config
└── views/           # Page components: Dashboard, NetworkMap, Nodes, PXEDeploy,
                     #   Alerts, Patrol, Diagnose
```

`NetworkMap.vue` renders a D3.js three-plane topology graph. The backend API base URL is
configured per-view via Axios (proxied through Vite in dev mode).

## Runtime data / secrets

`backend/pxe_data/` (node MACs, BMC addresses and credentials), `backend/cluster_manager.db`,
`backend/iso/` and `backend/ssh_credentials.json` are runtime state and are **not** tracked —
see `.gitignore`. Copy the templates in `backend/pxe_data_example/` to get started, and never
commit real credentials.
