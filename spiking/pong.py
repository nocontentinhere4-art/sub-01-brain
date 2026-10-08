"""Pong for the spiking network (after DishBrain: Kagan et al. 2022, Neuron 110:3952, "In vitro neurons learn and
exhibit sentience when embodied in a simulated game-world"; we reuse the task design, not the claim).

Field: unit square, y = 0 at the top; the paddle (height 0.2) moves vertically on the left edge, the ball bounces
off the top, bottom and right walls. One rally = one approach of the ball to the paddle (hit or miss).

Sensory encoding (every 10 ms) into the visual parcels, as extra drive (mV) on their neurons:
- horizontal position -> hemisphere: ball in the left half of the field (left visual field) drives right-hemisphere
  visual parcels, right half drives the left hemisphere (smooth crossover around the midline);
- vertical position of the ball relative to the paddle (as in DishBrain) -> place code over dorsal/ventral visual
  parcels: ball above the paddle (upper visual field) -> ventral parcels (lowest centroids), below -> dorsal parcels
  (retinotopy: upper field maps below the calcarine sulcus). Each parcel has a preferred elevation from its
  superior-inferior rank within its hemisphere and a Gaussian tuning curve.
Motor read-out: paddle velocity = v_max * tanh(z / 2), z = (rate of left-hemisphere somatomotor neurons - rate of
right-hemisphere ones), 50 ms smoothing, centred and scaled by its own running mean and sd (10 s). Positive z
moves the paddle up.
Feedback: hit -> phasic dopamine (reward-prediction error 1 - p_hit, at least 0.2); miss -> 500 ms of unpredictable
stimulation (random visual parcels re-drawn every 50 ms), as in DishBrain. Chat can add a small "good!" pulse
(0.3, rate-limited), always below the hit reward.
Controls: the same network with plasticity frozen, and a random paddle (an Ornstein-Uhlenbeck z with the same
statistics, no network).
"""
import math

import numpy as np
import torch

FRAME_MS = 10


class Game:
    def __init__(self, rng, paddle_h=0.2, speed=0.8, ball_r=0.02):
        self.rng, self.h, self.speed, self.r = rng, paddle_h, speed, ball_r
        self.paddle = 0.5
        self.hits = self.misses = self.rally = 0
        self.reset()

    def reset(self):
        self.x = 0.85
        self.y = self.rng.uniform(0.1, 0.9)
        ang = self.rng.uniform(-0.6, 0.6)
        self.vx, self.vy = -self.speed * math.cos(ang), self.speed * math.sin(ang)

    def step(self, dt, v_paddle):
        """Advance dt seconds; returns 'hit', 'miss' or None."""
        self.paddle = float(np.clip(self.paddle - v_paddle * dt, self.h / 2, 1 - self.h / 2))   # +v = up
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.y < self.r or self.y > 1 - self.r:
            self.vy = -self.vy
            self.y = float(np.clip(self.y, self.r, 1 - self.r))
        if self.x > 1 - self.r:
            self.vx = -abs(self.vx)
        if self.x <= self.r:
            self.rally += 1
            if abs(self.y - self.paddle) <= self.h / 2 + self.r:
                self.hits += 1
                self.vx = abs(self.vx)
                self.vy = float(np.clip(self.vy + self.rng.normal(0, 0.15), -0.55, 0.55))   # spin, bounded
                self.x = self.r
                return "hit"
            self.misses += 1
            self.reset()
            return "miss"
        return None

    def frame(self):
        return {"ball": [round(self.x, 3), round(self.y, 3)], "paddle": round(self.paddle, 3), "paddle_h": self.h,
                "hits": self.hits, "misses": self.misses, "rally": self.rally}


class PongInterface:
    """Encoder (ball -> visual drive) and decoder (somatomotor L-R -> paddle) on a SpikingNet."""

    def __init__(self, net, amp=4.0, sigma=0.3, v_max=1.5, seed=0):
        self.net, self.amp, self.sigma, self.v_max = net, amp, sigma, v_max
        reg = net.reg
        self.vis = reg.groups["visual"]
        self.hemi = np.array([reg.hemisphere(i) for i in range(reg.n)])
        self.pref = np.zeros(reg.n)
        for h in "LR":
            ids = [i for i in self.vis if self.hemi[i] == h]
            order = np.argsort(reg.centroids[ids, 2])                 # inferior (ventral) -> superior (dorsal)
            # ventral parcels prefer the ball above the paddle (dy < 0), dorsal ones below (dy > 0)
            self.pref[np.array(ids)[order]] = np.linspace(-0.8, 0.8, len(ids))
        sm = reg.groups["somatomotor"]
        self.sm_l = [i for i in sm if self.hemi[i] == "L"]
        self.sm_r = [i for i in sm if self.hemi[i] == "R"]
        self.size = net.size
        self.rng = np.random.default_rng(seed)
        self.z_mean, self.z_var = 0.0, 0.01
        self.calibrated = False
        self.diff_ema = 0.0
        self.last_rc = None
        self.stim_until = -1
        self.noise_z = 0.0

    def encode(self, game):
        """Visual drive (mV per region) for the current ball position."""
        drive = np.zeros(self.net.reg.n)
        right_field = 1.0 / (1.0 + math.exp(-(game.x - 0.5) / 0.08))    # 1 = right half of the field
        dy = float(np.clip((game.y - game.paddle) / 0.5, -1, 1))        # <0: ball above the paddle
        for i in self.vis:
            w_h = right_field if self.hemi[i] == "L" else 1.0 - right_field
            drive[i] = self.amp * w_h * math.exp(-((dy - self.pref[i]) ** 2) / (2 * self.sigma ** 2))
        return drive

    def unpredictable(self):
        drive = np.zeros(self.net.reg.n)
        on = self.rng.random(len(self.vis)) < 0.3
        drive[np.array(self.vis)[on]] = 6.0
        return drive

    def motor(self, dt_ms):
        """z-scored L-R somatomotor rate difference over the last frame (smoothed 50 ms)."""
        rc = self.net.region_count.cpu().numpy().copy()       # copy: on CPU .numpy() aliases the live counter
        if self.last_rc is None:
            self.last_rc = rc
            return 0.0
        d = (rc - self.last_rc) / (dt_ms / 1000.0)
        self.last_rc = rc
        r_l = d[self.sm_l].sum() / self.size[self.sm_l].sum()
        r_r = d[self.sm_r].sum() / self.size[self.sm_r].sum()
        k = math.exp(-dt_ms / 50.0)
        self.diff_ema = k * self.diff_ema + (1 - k) * (r_l - r_r)
        a = dt_ms / 10_000.0
        self.z_mean += a * (self.diff_ema - self.z_mean)
        self.z_var += a * ((self.diff_ema - self.z_mean) ** 2 - self.z_var)
        return (self.diff_ema - self.z_mean) / math.sqrt(self.z_var + 1e-9)

    def calibrate(self, game, ms=5000):
        """Settle the read-out statistics (running mean / sd of L-R) with random ball positions, paddle still."""
        rng = np.random.default_rng(1)
        for k in range(ms // FRAME_MS):
            if k % 50 == 0:
                game.x, game.y = rng.uniform(0.05, 0.95), rng.uniform(0.05, 0.95)
                self.net.set_region_drive("pong", self.encode(game))
            self.net.run(FRAME_MS)
            self.motor(FRAME_MS)
        game.reset()
        self.calibrated = True

    def velocity(self, z):
        return self.v_max * math.tanh(z / 2.0)

    def random_z(self, dt_ms):
        """Ornstein-Uhlenbeck z (unit variance, 50 ms correlation) for the random-paddle control."""
        k = math.exp(-dt_ms / 50.0)
        self.noise_z = k * self.noise_z + math.sqrt(1 - k * k) * self.rng.normal()
        return self.noise_z


class Pong:
    """Runs rallies on the network. mode: 'train' (plasticity on), 'exam' (frozen), 'random' (no network)."""

    def __init__(self, net, seed=0, reward=1.0, good_pulse=0.3, on_frame=None):
        self.net = net
        self.io = PongInterface(net, seed=seed)
        self.game = Game(np.random.default_rng(seed + 7))
        self.reward, self.good_pulse = reward, good_pulse
        self.p_hit = 0.3
        self.on_frame = on_frame
        self.shown = self.game                 # the game currently on screen (exams use their own ball sequences)
        self.dopamine_level = 0.0
        self.last_good = -1e9
        self.curve = []
        self.abs_v = []                    # mean |paddle velocity| per play() call (is the paddle moving at all?)

    def good(self):
        """Chat 'good!': small dopamine pulse, at most one per 30 s of simulated time, always < the hit reward."""
        t = self.net.t * self.net.cfg.dt
        p = self.net.plast
        if p is None or p.frozen or t - self.last_good < 30_000:
            return False
        self.last_good = t
        p.dopamine(min(self.good_pulse, 0.5 * self.reward))
        return True

    def play(self, rallies, mode="train", game_seed=None):
        """Play `rallies` approaches; returns (hits, rallies). game_seed: a fresh, reproducible ball sequence
        (exams use the same seeds before/after training and for the controls -> paired comparisons)."""
        net, io, p = self.net, self.io, self.net.plast
        g = self.game if game_seed is None else Game(np.random.default_rng(game_seed))
        frozen_before = p.frozen if p is not None else None
        if p is not None:
            p.frozen = True
        try:
            if mode != "random" and not io.calibrated:
                io.calibrate(g)
            if p is not None:
                p.frozen = mode != "train"
            io.last_rc = None                                    # no rate over a gap since the last play()
            h0, r0 = g.hits, g.rally
            stim_left = 0
            vsum, vn = 0.0, 0
            while g.rally - r0 < rallies:
                if stim_left > 0:                                # after a miss: the game pauses, noise plays
                    if stim_left % 50 == 0:
                        net.set_region_drive("pong", io.unpredictable())
                    net.run(FRAME_MS)
                    io.motor(FRAME_MS)
                    stim_left -= FRAME_MS
                    if self.on_frame is not None:
                        self.on_frame(self)
                    continue
                if mode == "random":
                    z = io.random_z(FRAME_MS)
                else:
                    net.set_region_drive("pong", io.encode(g))
                    net.run(FRAME_MS)
                    z = io.motor(FRAME_MS)
                v = io.velocity(z)
                vsum, vn = vsum + abs(v), vn + 1
                ev = g.step(FRAME_MS / 1000.0, v)
                if ev is not None and mode == "train":
                    expected = self.p_hit                        # reward-prediction error vs the prior expectation
                    self.p_hit += 0.05 * ((ev == "hit") - self.p_hit)
                    if ev == "hit" and p is not None:
                        p.dopamine(self.reward * max(0.2, 1.0 - expected))
                if ev == "miss" and mode != "random":
                    stim_left = 500
                if self.on_frame is not None and mode != "random":
                    self.on_frame(self)
        finally:
            net.set_region_drive("pong", None)
            if p is not None:
                p.frozen = frozen_before
        self.abs_v.append(round(vsum / max(1, vn), 3))
        self.shown = g
        return g.hits - h0, g.rally - r0

    def train(self, blocks, block_rallies=20, on_block=None):
        for b in range(blocks):
            h, n = self.play(block_rallies, "train")
            self.curve.append({"block": len(self.curve), "rallies": n, "hit_rate": round(h / n, 4),
                               "mean_abs_v": self.abs_v[-1]})
            if on_block:
                on_block(self.curve[-1])
        return self.curve

    def exam(self, rallies=20, game_seed=None):
        h, n = self.play(rallies, "exam", game_seed=game_seed)
        return {"rallies": n, "hits": h, "hit_rate": round(h / n, 4), "frozen": True, "mean_abs_v": self.abs_v[-1]}


def random_paddle(rallies=2000, seed=0):
    """Hit rate of a random paddle (no network) — the chance baseline."""
    io = PongInterface.__new__(PongInterface)
    io.rng, io.noise_z, io.v_max = np.random.default_rng(seed), 0.0, 1.5
    g = Game(np.random.default_rng(seed + 7))
    while g.rally < rallies:
        z = PongInterface.random_z(io, FRAME_MS)
        g.step(FRAME_MS / 1000.0, PongInterface.velocity(io, z))
    return {"rallies": g.rally, "hits": g.hits, "hit_rate": round(g.hits / g.rally, 4)}


def tracking_paddle(rallies=500, seed=0):
    """An ideal tracker (moves toward the ball at v_max) — the ceiling of the task."""
    g = Game(np.random.default_rng(seed + 7))
    while g.rally < rallies:
        v = 1.5 * np.sign(g.paddle - g.y)                            # +v moves up (towards smaller y)
        g.step(FRAME_MS / 1000.0, v)
    return {"rallies": g.rally, "hits": g.hits, "hit_rate": round(g.hits / g.rally, 4)}
