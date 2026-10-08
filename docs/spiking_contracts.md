# SUB-01 v3 spiking brain — interface contracts

Shared by every piece of `spiking/`. If you must change an interface, say so in your final summary.

Wording rule for every file, comment, doc and page string: *one million simulated spiking neurons inside the real
wiring of one person's brain; a model, not a mind; not the person*. Never name the MyConnectome participant or write
as if speaking for them. No consciousness / "alive" claims. No financial content in generated text. No secrets in git
or logs (never print an API key, pod secret or Authorization header).

## Package layout (all new code lives in `spiking/`, tests in `tests/test_spiking_*.py`)

| file | runs on | owner | purpose |
|---|---|---|---|
| `spiking/config.py` | both | core | `Config` dataclass, presets `small()` (20k) / `full()` (1M), `config_hash()` |
| `spiking/regions.py` | both | core | load connectome / names / volumes / groups (no import of `brain_sim`) |
| `spiking/net.py` | both | core | `SpikingNet` (build, step, inputs, recording) |
| `spiking/plasticity.py` | both | core | three-factor STDP, modulators, homeostasis, learned-weight file I/O |
| `spiking/memory.py` | both | core | word hashing -> patterns, encoding, recall test, REM replay/consolidation |
| `spiking/pong.py` | both | core | game, visual encoder, motor decoder, training / exam / controls |
| `spiking/session.py` | pod | core | `python -m spiking.session`: runs a session, streams to the server, uploads weights |
| `spiking/podpack.py` | sandbox + Railway | ops | pack code+data into env vars, build the pod create body |
| `spiking/costs.py` | sandbox + Railway | ops | append-only cost log (`costs.jsonl`), totals |
| `spiking/pod_manager.py` | Railway | ops | schedule (`SUB01_SESSIONS`), start/stop/delete pods, hard caps |
| `spiking/server.py` | Railway | ops | aiohttp routes: pod websocket ingress, weights store, status for the page |
| `spiking/validate.py` | sandbox | ops | `python -m spiking.validate --gpu` (or `--cpu`) |

## RunPod rules (hard)

- GPU type `"NVIDIA RTX A5000"`, fallback `"NVIDIA RTX 4000 Ada Generation"`; `gpuCount` 1; `interruptible: false`
  (on-demand); `cloudType: "SECURE"`; image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`;
  `containerDiskInGb: 30`; `volumeInGb: 0` (no paid volume); `ports: ["8000/http"]`.
- REST base `https://rest.runpod.io/v1` via `runpod_api.api(path, method, body)` (adds `Authorization` only when
  `RUNPOD_API_KEY` exists; in the sandbox the egress proxy injects it).
- Every pod we create: name starts with `sub01-spiking-`; deleted (`DELETE /pods/{id}`) when its job ends, on any
  error, and at the latest after `max_minutes` (default 60). Never more than 1 of our pods at a time (check
  `GET /pods` for names starting `sub01-spiking-` before creating). Never stop/modify/delete a pod whose name does not
  start with `sub01-spiking-` (e.g. the user's pod `BRAIN`).
- Budget cap: `SUB01_GPU_HOURS_CAP` (validation: 4.0 GPU-hours over the whole cost log; Railway: 8.0 over a rolling
  `SUB01_GPU_CAP_DAYS`=7 days); per-day cap `SUB01_MAX_HOURS_PER_DAY` (default 1.0); per-session cap
  `SUB01_MAX_SESSION_MIN` (default 60, from pod creation, on Railway and for validation).
- Cost log: one JSON line per pod in `<data_dir>/spiking/costs.jsonl`:
  `{"pod_id", "name", "gpu", "cost_per_hr", "start": iso, "stop": iso, "hours", "cost_usd", "reason", "purpose"}`
  (written on stop; a `{"event":"start", ...}` line is written at creation so a crash still leaves a trace).

## Pod start (no GitHub credentials)

`podpack.pack(files) -> {"SUB01_PACK_0": b64, "SUB01_PACK_1": ...}`: tar.xz of the listed files, base64, split in
chunks of <= 96 000 characters. `podpack.start_cmd()` -> `["bash", "-c", "<script>"]` where the script:

```
mkdir -p /app /out && cd /app
python3 -c "import os,base64,io,tarfile; ks=sorted((k for k in os.environ if k.startswith('SUB01_PACK_')), key=lambda k:int(k.rsplit('_',1)[1])); tarfile.open(fileobj=io.BytesIO(base64.b64decode(''.join(os.environ[k] for k in ks))), mode='r:xz').extractall('/app')"
(python3 -m http.server 8000 -d /out >/dev/null 2>&1 &)
python3 -m spiking.session > /out/session.log 2>&1; echo $? > /out/exit_code; sleep 600
```

The packed files: `spiking/*.py`, `spiking/region_volumes.json`, `real_baseline.py`, `out/connectome.npz`,
`out/atlas_names.json`, `out/rest/qc.json` and a few resting-state runs re-saved as float16 (`podpack.rest_subset`).
Results are read at `https://<podId>-8000.proxy.runpod.net/<file>` (no key needed): `status.json` (always present,
updated every few seconds: `{"phase", "progress", "t_sim", "done": bool, "error": str|null}`), `results.json`,
`session.log`, `weights.npz` when present.

Pod env: `SUB01_PACK_*`, `SUB01_SESSION` (JSON, below), optional `SUB01_SERVER_URL` (https base of the Railway app),
optional `SUB01_POD_SECRET`, `SUB01_SESSION_ID`.

## Session config (`SUB01_SESSION` JSON)

```json
{"session_id": "s-20261001-2100", "day": "2026-10-01", "n_neurons": 1000000, "seed": 1,
 "max_minutes": 110, "phases": ["encode", "pong_train", "pong_exam", "memory_test", "sleep", "memory_test", "free"],
 "pong_train_minutes": 20, "messages": [{"text": "...", "emotion": "positive"}], "elapsed_days": 1.0,
 "validate": false}
```

## Pod -> server (websocket `wss://<server>/api/spiking/pod?session=<id>`, header `Authorization: Bearer <SUB01_POD_SECRET>`)

All JSON text frames.
- `{"type":"hello","session":id,"n_neurons":int,"device":str,"phases":[...]}`
- `{"type":"state", ...}` about 4 per second:
  `{"t_sim": s, "phase": str, "n_neurons": int, "spikes_per_s": float (network total, sim time),
    "mean_rate_hz": float, "steps_per_s": float, "realtime_x": float,
    "groups": {"visual": Hz, "somatomotor": Hz, ..., "memory": Hz},  # same group keys as brain_sim.GROUPS + "language"
    "raster": {"n": rows, "t0": ms, "t1": ms, "spikes": [[t_ms_rel, row], ...]},  # <= 200 rows, last 250 ms
    "pong": {"ball": [x, y], "paddle": y, "paddle_h": h, "hits": int, "misses": int, "rally": int} | null,
    "dopamine": float}`
- `{"type":"result","kind":"pong_curve","points":[{"block":i,"rallies":n,"hit_rate":p}], "controls": {...}}`
- `{"type":"result","kind":"exam","day":d,"rallies":20,"hits":k,"hit_rate":p,"frozen":true,"controls":{"random":p,"no_plasticity":p}}`
- `{"type":"result","kind":"memory_test","day":d,"cues":[...],"recalled":[...],"scores":[...],"control_scores":[...]}`
- `{"type":"result","kind":"bench","steps_per_s":..,"realtime_x":..,"n_neurons":..,"synapses":..,"gpu":..}`
- `{"type":"done","ok":bool,"error":str|null}`

## Server -> pod (same websocket)

- `{"type":"chat","text":str,"emotion":str}` (already filtered by chat.py on the server)
- `{"type":"good"}` — chat "good!" dopamine pulse; rate-limited on the server (1 per 30 s) and on the pod; its
  amplitude is always < the task hit reward.
- `{"type":"sleep","stage":"AWAKE"|"NREM"|"REM"}` — the sleep engine stage
- `{"type":"stop"}`

## Learned weights (stored on Railway under `<data_dir>/spiking/`)

- `GET  <server>/api/spiking/weights` (Bearer secret) -> `weights.npz` bytes or 404.
- `POST <server>/api/spiking/weights` (Bearer secret, body = npz, streamed, cap 512 MB) -> 200.
- `POST <server>/api/spiking/result` (Bearer secret, JSON result) -> appended to `memory_tests.jsonl` /
  `exams.jsonl` / `pong_curves.jsonl` (also accepted over the websocket).
- These pod routes bypass the site password gate but require `hmac.compare_digest` on the pod secret; without
  `SUB01_POD_SECRET` set on the server they return 403.

## Page status (`GET /api/spiking/status`, behind the password gate like every `/api/` route)

```json
{"live": bool, "session": {...}|null, "next_session": iso|null, "last": {"exam": {...}, "memory_test": {...},
 "pong_curve": {...}, "bench": {...}}, "spend": {"total_usd": x, "hours": h}}
```
While live, every pod `state` frame is relayed to the page websocket as `{"type":"spiking", ...state}`.
