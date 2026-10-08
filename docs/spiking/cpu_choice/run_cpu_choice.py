"""CPU runs behind docs/spiking/choice.md: python docs/spiking/cpu_choice/run_cpu_choice.py N TRIALS NET_SEED TASK_KW_JSON OUT.json
(run from the repo root with PYTHONPATH=.; a frozen twin network with the same seed is the control)."""
import time, sys, json, torch
torch.set_num_threads(1)
from spiking.config import Config
from spiking.net import SpikingNet
from spiking.choice import experiment
N=int(sys.argv[1]); trials=int(sys.argv[2]); ns=int(sys.argv[3]); kw=json.loads(sys.argv[4]); outp=sys.argv[5]
t=time.time()
net=SpikingNet(Config(n_neurons=N, seed=ns)); net.run(300); net.plast.set_stdp(False)
twin=SpikingNet(Config(n_neurons=N, seed=ns)); twin.run(300); twin.plast.set_stdp(False)
out=experiment(net, trials=trials, frozen_net=twin, seed=ns, **kw); out.pop("task")
out.update(n_neurons=N, net_seed=ns, task_kw=kw, wall_s=round(time.time()-t,1), sim_s=round(net.t/1000,1))
json.dump(out, open(outp,"w"), indent=1)
print(outp, "done", out["wall_s"])
