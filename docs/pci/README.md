# The PCI test on SUB-01's brain model (2026-10-01)

`analysis/pci_test.py` runs the perturbational complexity index (Casali et al. 2013) on the deployed model:
a sudden kick to one region (left posterior parietal or right sensorimotor), 60 trials per state, sleep-stage
parameters from `sleep.py`, 300 ms after the pulse in 2 ms bins, a bootstrap of the baseline maximum (alpha 0.01),
normalised Lempel-Ziv complexity of the significant response.

| state | PCI (model) | people (Casali 2013) |
|---|---|---|
| awake | 0.18 | 0.44-0.67 |
| deep sleep (NREM) | 0.07 | 0.18-0.28 |
| REM | 0.17 | — |
| anaesthesia | — | 0.12-0.31 |

Clinical cut-off: 0.31 (Casarotto et al. 2016).

**What it shows.** The ordering is the human one (awake ≈ REM > deep sleep), but every value is below the
cut-off. The pulse stays where it lands: the struck region responds ~126x above noise, the strongest other
regions ~7-9x, under the significance threshold. A local, short-lived echo is the signature of deep sleep and
anaesthesia in people.

**Robustness.**
- 200 trials with a 2x pulse: 0.12 / 0.07 / 0.12 (`docs/pci/robust/`).
- 5x inter-region coupling: still local, about 0.2 (`docs/pci/coupling5x/`).
- With almost nothing significant beyond one region, the exact values are fragile. The robust finding is that
  the perturbation does not spread.

**What it does not show.** PCI is validated on human brains, where it tracks reported experience. A model scoring
high would not be conscious, and a model scoring low says nothing about experience either: it says this model's
fast layer is too damped and weakly coupled to carry a perturbation across the brain. That matches
`analysis/null_test.py`: the fast 10 Hz layer barely uses the wiring.
