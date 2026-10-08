"""How many spiking neurons can one GPU run in real time? (leaky integrate-and-fire, event-driven synapses)

80% excitatory / 20% inhibitory, K random outgoing synapses per neuron (sparse CSR), dt = 1 ms, Poisson drive.
Real time = 1000 steps per wall-clock second. Writes one JSON line per size.
"""
import json
import time

import torch

dev = "cuda"
torch.manual_seed(0)
print(json.dumps({"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__}), flush=True)


def build(n, k):
    ne = int(0.8 * n)
    src = torch.arange(n, device=dev).repeat_interleave(k)
    dst = torch.randint(0, n, (n * k,), device=dev)
    w = torch.where(src < ne, torch.full_like(src, 1, dtype=torch.float32) * 0.2,
                    torch.full_like(src, 1, dtype=torch.float32) * -1.0)
    # outgoing rows in CSR order by source
    rowptr = torch.arange(0, n * k + 1, k, device=dev)
    return rowptr, dst, w


def run(n, k, steps=1000):
    rowptr, dst, w = build(n, k)
    v = torch.rand(n, device=dev) * 10
    refr = torch.zeros(n, device=dev)
    tau, vth, vreset, dt = 20.0, 20.0, 0.0, 1.0
    mu_ext, sd_ext = 0.95, 1.6                    # background input (mV/ms): cortex-like low firing, 1-10 Hz
    spikes_total = 0
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(steps):
        ext = mu_ext * dt + sd_ext * torch.randn(n, device=dev)
        v = v + dt * (-v / tau) + ext
        v = torch.where(refr > 0, torch.full_like(v, vreset), v)
        spk = (v >= vth).nonzero().squeeze(1)
        spikes_total += spk.numel()
        v[spk] = vreset
        refr = (refr - dt).clamp_(min=0)
        refr[spk] = 2.0
        if spk.numel():                           # event-driven: only rows of neurons that fired
            idx = (rowptr[spk].unsqueeze(1) + torch.arange(k, device=dev)).reshape(-1)
            v.index_add_(0, dst[idx], w[idx])
    torch.cuda.synchronize()
    wall = time.time() - t0
    return {"neurons": n, "synapses_per_neuron": k, "synapses": n * k, "wall_s_per_sim_s": round(wall, 3),
            "realtime_x": round(1.0 / wall, 2), "mean_rate_hz": round(spikes_total / n, 1),
            "gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)}


for n, k in [(250_000, 100), (1_000_000, 100), (2_000_000, 100), (4_000_000, 100), (8_000_000, 100),
             (1_000_000, 1000), (2_000_000, 500)]:
    try:
        run(min(n, 10000), k, 50)                 # warm-up
        print(json.dumps(run(n, k)), flush=True)
    except torch.cuda.OutOfMemoryError:
        print(json.dumps({"neurons": n, "synapses_per_neuron": k, "error": "out of GPU memory"}), flush=True)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
