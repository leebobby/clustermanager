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

### Product → machine type → role

Templates live in `backend/node_templates.json` — a file, never the DB.

- **Product** (`products[]`) defines the roles: hostname prefix, which network planes each
  role attaches to, subnet prefixes, IP start offsets, hardware specs, per-role checks.
- **Machine type** (`machine_types[]`) only says how many of each role.
- **Role** is identified by `roles[].key` (`host` / `master` / `slave` / `subswath` /
  `gstorage`), mirrored onto `nodes.role_key`. The key is the anchor between a node and its
  role definition — **never** derive role identity from the hostname prefix, which users
  are free to rename.

There is **no cluster entity**. The tool faces one machine at a time: the chosen
(product, machine type) lives in `backend/workspace.json`, and `workspace_service.sync_nodes()`
materializes the template into `nodes`, idempotently. Switching machine type rebuilds the
node set — `master-01` exists under both types, so the old set must go or hostnames collide.
Hand-added nodes (`role_key` empty) survive a sync. `nodes.cluster_id` and the `clusters`
table are leftovers from an earlier design: never read, never written; SQLite makes dropping
columns awkward, so they stay in old DBs.

**A role can have several NICs on one plane.** `planes[].prefixes` is a list — Master has
four data-plane IPs (two DPDK front + two RDMA back). `plan_node()` writes them to
`nodes.plane_ips` ({plane: [ip, …]}); the flat `mgmt_ip` / `ctrl_ip` / `data_ip` columns keep
only the first one so older code (PXE, network API) still works. Diagnosis probes every IP
separately — collapsing four ports into one check hides the broken one. `nodes.plane_status`
({plane: online|offline}) is what the topology colors links by.

`template_service._migrate()` upgrades three historical formats in place (`templates` →
`projects` → `products`). When migrating from `projects`, `machine_types[].counts` are keyed
by hostname prefix and must be re-keyed to `roles[].key`, or every count silently becomes 0.

`topology_service.build()` draws the whole network map from a template alone — no DB, no
live nodes needed. Passing `nodes` overlays real status on the same fixed layout.

`diag_plan.build_plan()` derives the check list from that topology, then `select()` filters it
by the checks and roles the user ticked — running everything is impractical in the field, so
the UI ticks first and runs second. `options()` returns an exact (check × role) count matrix;
the UI sums it rather than estimating, because showing a wrong count is worse than none.
Checks with no script claiming them are reported as `skip` with a reason, never folded into
"pass". A probe tool that is missing (no `ping` on the box) is also `skip`, never `fail` —
that is our problem, not the node's.

`services/probe.py` does the real reachability probing (`network_service.check_connectivity`
and `api/network.check_node_network` still return simulated values — do not build on them).

## Frontend architecture

```
frontend/src/
├── main.js          # App entry, Element Plus setup
├── App.vue          # Root layout: 4-item sidebar + persistent cluster picker
├── router/          # Vue Router config
├── stores/          # workspace.js — the one piece of shared state (current machine type)
├── styles/          # theme.css — all colors, as CSS variables
└── views/           # Checkup (一键诊断, landing), NetworkMap, Clusters, Diagnose
                     #   (告警与日志), Alerts; unrouted: Dashboard, PXEDeploy, Patrol
```

`NetworkMap.vue` uses a **fixed layout**, not a force-directed graph: three horizontal plane
buses with role groups hanging beneath them. Positions are identical on every open, and node
count only changes how many chips are in a group. D3 is no longer a dependency.

Buses always carry the plane's own color (they answer "which plane is this"). In **live**
mode the vertical stubs switch to status color, thicken when broken, and get an X marker plus
an up/total tally — colour is never the only channel. The X sits just below the junction, not
at the stub midpoint, or it lands on an unrelated bus and reads as that bus being down.

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
