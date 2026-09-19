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
├── api/             # Route handlers: clusters, templates, nodes, network, alerts, diagnose,
│                    #   ipmi, patrol, pxe, firmware
└── services/        # Business logic: template_service, topology_service, diag_plan, probe,
                     #   ipmi_service, network_service, pxe_service, redfish_service,
                     #   diag_service, cred_service
```

### Product → machine type → cluster → role

The data model has four levels. The first two live in `backend/node_templates.json`
(a file, never the DB); the last two live in SQLite.

- **Product** (`products[]`) defines the roles a product's clusters are built from:
  hostname prefix, which network planes each role attaches to, subnet prefixes,
  IP start offsets, hardware specs, and which per-role checks apply.
- **Machine type** (`machine_types[]`) only says how many of each role. Everything else
  is inherited from the product.
- **Cluster** (`clusters` table) is one physical machine in the field. Creating one expands
  the template into nodes, each stamped with `cluster_id`.
- **Role** is identified by `roles[].key` (`host` / `master` / `slave` / `subswath` /
  `gstorage`), mirrored onto `nodes.role_key`. The key is the anchor between a node and its
  role definition — **never** derive role identity from the hostname prefix, which users
  are free to rename.

`template_service._migrate()` upgrades three historical formats in place (`templates` →
`projects` → `products`). When migrating from `projects`, `machine_types[].counts` are keyed
by hostname prefix and must be re-keyed to `roles[].key`, or every count silently becomes 0.

`topology_service.build()` draws the whole network map from a template alone — no DB, no
live nodes needed. Passing `nodes` overlays real status on the same fixed layout.

`diag_plan.build_plan()` derives the check list from that topology. Checks with no script
claiming them are reported as `skip` with a reason, never folded into "pass".

`services/probe.py` does the real reachability probing (`network_service.check_connectivity`
and `api/network.check_node_network` still return simulated values — do not build on them).

## Frontend architecture

```
frontend/src/
├── main.js          # App entry, Element Plus setup
├── App.vue          # Root layout: 4-item sidebar + persistent cluster picker
├── router/          # Vue Router config
├── stores/          # cluster.js — the one piece of shared state (current cluster)
├── styles/          # theme.css — all colors, as CSS variables
└── views/           # Checkup (一键诊断, landing), NetworkMap, Clusters, Diagnose
                     #   (告警与日志), Alerts; unrouted: Dashboard, PXEDeploy, Patrol
```

`NetworkMap.vue` uses a **fixed layout**, not a force-directed graph: three horizontal plane
buses with role groups hanging beneath them. Positions are identical on every open, and node
count only changes how many chips are in a group. D3 is no longer a dependency.

### Colors

Every color comes from `src/styles/theme.css` — do not hardcode hex values in a view.
Three sets, which must not be mixed:

- **Base** (`--cm-bg`, `--cm-surface`, `--cm-text`, `--cm-brand`) — page chrome, no meaning.
- **Status** (`--cm-ok` / `--cm-warn` / `--cm-crit` / `--cm-idle`) — the *only* channel for
  health. Red appears nowhere else in the UI; that was the reason for dropping the old
  `#e94560` accent, which meant both "selected" and "fault".
- **Plane** (`--cm-plane-*`) — topology lines only; all four deliberately avoid red/amber/green.

The theme also feeds Element Plus's own CSS variables, so components follow without
`:deep()` overrides. The log console in `Diagnose.vue` stays dark on purpose.

## Runtime data / secrets

`backend/pxe_data/` (node MACs, BMC addresses and credentials), `backend/cluster_manager.db`,
`backend/iso/` and `backend/ssh_credentials.json` are runtime state and are **not** tracked —
see `.gitignore`. Copy the templates in `backend/pxe_data_example/` to get started, and never
commit real credentials.
