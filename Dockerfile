FROM python:3.12-slim
WORKDIR /app
COPY requirements-server.txt .
# small 214-region matrices: BLAS threads only spin, and the CPU is shared with the screens' browser
ENV PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 BROWSE=1
# Chromium outside /root, so uid 1000 can start it
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# #59: ffmpeg (H.264) + DejaVu fonts for the daily clips (clips.py renders in nice'd children)
RUN pip install --no-cache-dir -r requirements-server.txt \
 && python -m playwright install --with-deps --only-shell chromium \
 && apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
# #18: the server and Chromium run as sub01 (uid 1000), so Chromium can keep its sandbox. The image still starts as root:
# entrypoint.sh hands the root-owned /data volume to uid 1000 and drops privileges with setpriv (util-linux, already in
# Debian slim). No `USER` line on purpose: a container that starts as uid 1000 cannot fix a root-owned volume.
# RUN_AS_ROOT=1 keeps everything root as before (rollback; Chromium back on --no-sandbox).
COPY entrypoint.sh /usr/local/bin/sub01-entrypoint
RUN chmod 755 /usr/local/bin/sub01-entrypoint \
 && useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin sub01 \
 && mkdir -p /data/frames && chown -R 1000:1000 /data
COPY audience.py brain_sim.py sleep.py chat.py eye.py real_baseline.py life.py live_server.py diary.py research.py browse.py launchpad_eval.py \
     runpod_api.py browse_service.py eyes.py brain_vote.py tastes.py state_io.py mind.py costs.py chess_game.py \
     search_sources.py sessions.py view_only.py interests.py short_videos.py music.py music_curated.json clips.py readings.py screens.py novelty.py youtube_api.py memory_guard.py lexicon.py ./
COPY twin ./twin
COPY spiking ./spiking
COPY web ./web
COPY out/connectome.npz out/atlas_names.json ./out/
COPY out/rest ./out/rest
# /data is a persistent volume: sleep state, memory, nights, world, eye frames, browsing log
# BROWSE=1: his computer and phone screens show real web pages (headless Chromium); set BROWSE=0 to turn it off.
# Chromium runs in its own process (browse_service.py, a child with a memory watchdog). To run it as a separate Railway
# service instead: same repo, start command `python browse_service.py --host :: --port $PORT`, no public domain,
# BROWSE_SERVICE_TOKEN set on both services, and BROWSE_SERVICE_URL=http://<service>.railway.internal:<port> here.
ENTRYPOINT ["/usr/local/bin/sub01-entrypoint"]
# `exec`: python is PID 1 (not sh), so Railway's SIGTERM at a redeploy reaches it and live_server.py saves its state
CMD ["sh", "-c", "exec python live_server.py --host 0.0.0.0 --port ${PORT:-8080} --eye --trust-proxy --data-dir /data --frames-dir /data/frames ${EXTRA_ARGS:-}"]
