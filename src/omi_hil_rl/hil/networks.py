"""No-gripper multimodal Gaussian actor, twin critics and SAC updates."""
from copy import deepcopy
import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from omi_hil_rl.training.eef_bc_stack import CurrentStackPolicy

VERSION = "omi-hil-sac-shared-serl-v2"
LEGACY_VERSION = "omi-hil-sac-no-gripper-v1"


def serl_head(inputs, outputs):
    # Official MLP activate_final=False: LN/tanh only after the first Dense.
    head = nn.Sequential(nn.Linear(inputs, 256), nn.LayerNorm(256, eps=1e-6),
                         nn.Tanh(), nn.Linear(256, 256), nn.Linear(256, outputs))
    for layer in head:
        if isinstance(layer, nn.Linear):
            nn.init.xavier_uniform_(layer.weight)
            nn.init.zeros_(layer.bias)
    return head


def augment_images(observation, padding=4):
    """Random crop with replicate padding; same shift for every history slot.

    Each sample/view has its own shift. Never modifies replay tensors.
    """
    result = dict(observation)
    for key in ('rgb', 'wrist_rgb'):
        value = observation[key]
        batch, slots, channels, height, width = value.shape
        padded = F.pad(value.reshape(batch, slots*channels, height, width).float(),
                       (padding, padding, padding, padding), mode='replicate')
        offsets = torch.randint(2*padding+1, (batch, 2), device=value.device)
        rows = offsets[:, 0, None, None] + torch.arange(height, device=value.device)[None, :, None]
        cols = offsets[:, 1, None, None] + torch.arange(width, device=value.device)[None, None, :]
        cropped = padded.permute(0, 2, 3, 1)[torch.arange(batch, device=value.device)[:, None, None], rows, cols]
        result[key] = cropped.permute(0, 3, 1, 2).reshape(value.shape).to(value.dtype)
    return result


class Encoder(nn.Module):
    def __init__(self, recipe):
        super().__init__()
        self.recipe = deepcopy(recipe)
        if recipe["encoder"] == "synthetic-test":
            self.model = nn.Sequential(nn.Linear(14 + 10, 128), nn.ReLU())
        elif recipe["encoder"] == "current9stack":
            self.model = CurrentStackPolicy(recipe["base_contract"], joint_mode="off")
            self.model.head = nn.Sequential(self.model.head[0], nn.ReLU())
            norm = recipe["normalization"]
            for name, shape in (("tactile_mean", (1, 1, 10, 1, 1)), ("tactile_std", (1, 1, 10, 1, 1)),
                                ("state_mean", (1, 1, 14)), ("state_std", (1, 1, 14))):
                value = torch.as_tensor(norm[name], dtype=torch.float32).reshape(shape)
                if not torch.isfinite(value).all() or (name.endswith("std") and not (value > 0).all()):
                    raise ValueError("invalid normalization: " + name)
                self.register_buffer(name, value)
        else:
            raise ValueError("unsupported encoder")
        self.use_wrench = bool(recipe.get('wrench_history', False))
        if self.use_wrench:
            if recipe['encoder'] != 'current9stack':
                raise ValueError('wrench history requires the real current9stack encoder')
            for name in ('wrench_mean', 'wrench_std'):
                value = torch.as_tensor(recipe['normalization'][name], dtype=torch.float32).reshape(1, 1, 2, 6)
                if not torch.isfinite(value).all() or (name.endswith('std') and not (value > 0).all()):
                    raise ValueError('invalid normalization: ' + name)
                self.register_buffer(name, value)
            # Chronological dual-finger six-vectors (120) + per-finger validity (20).
            self.wrench_encoder = nn.Sequential(nn.Linear(140, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU())
            self.wrench_fusion = nn.Sequential(nn.Linear(128 + 64, 128), nn.ReLU())
        self.eval()  # disable wrist dropout; trainable parameters still receive gradients

    def initialize_pretrained(self, weights):
        if self.recipe["encoder"] == "current9stack":
            self.model.initialize_pretrained(weights)

    def forward(self, obs):
        if self.recipe["encoder"] == "synthetic-test":
            state = obs["state"][:, -1].float().clone()
            state[:, :7] = 0
            return self.model(torch.cat((state, obs["tactile"][:, -1].float().mean((2, 3))), -1))
        x = (obs["rgb"].float() / 255.,
             (obs["tactile"].float() - self.tactile_mean) / self.tactile_std,
             (obs["state"].float() - self.state_mean) / self.state_std,
             obs["wrist_rgb"].float() / 255., obs["camera_mask"].float())
        features = self.model.forward_windows(x, obs["history_mask"].bool())
        if self.use_wrench:
            wrench = obs['wrench'].float()
            mask = obs['wrench_mask'].bool() & obs['history_mask'].bool()[:, :, None]
            if wrench.shape[1:] != (10, 2, 6) or mask.shape != wrench.shape[:-1]:
                raise ValueError('expected dual-finger ten-slot wrench history')
            normalized = torch.where(mask[..., None], (wrench - self.wrench_mean) / self.wrench_std, 0.)
            wrench_features = self.wrench_encoder(torch.cat((normalized.flatten(1), mask.float().flatten(1)), -1))
            features = self.wrench_fusion(torch.cat((features, wrench_features), -1))
        return features


class Actor(nn.Module):
    def __init__(self, recipe, encoder=None):
        super().__init__()
        self.encoder = encoder if encoder is not None else Encoder(recipe)
        self.head = serl_head(128, 12)
        # Equivalent to separate six-output mean/std Dense layers.
        nn.init.xavier_uniform_(self.head[-1].weight[:6])
        nn.init.xavier_uniform_(self.head[-1].weight[6:])

    def sample(self, observation, deterministic=False, *, detach_encoder=False):
        features = self.encoder(observation)
        if detach_encoder:
            features = features.detach()
        mean, log_std = self.head(features).chunk(2, -1)
        log_std = log_std.clamp(math.log(1e-5), math.log(5.))
        distribution = torch.distributions.Normal(mean, log_std.exp())
        raw = mean if deterministic else distribution.rsample()
        action = raw.tanh()
        # Stable tanh-Jacobian correction, including saturated actions.
        log_prob = (distribution.log_prob(raw) - 2 * (math.log(2) - raw - F.softplus(-2 * raw))).sum(-1, keepdim=True)
        return action, log_prob


class Critics(nn.Module):
    def __init__(self, recipe, encoder=None):
        super().__init__()
        self.encoder = encoder if encoder is not None else Encoder(recipe)
        self.heads = nn.ModuleList([serl_head(134, 1) for _ in range(2)])

    def forward(self, observation, action):
        x = torch.cat((self.encoder(observation), action), -1)
        return torch.stack([head(x) for head in self.heads], 0)


class LegacyActor(Actor):
    """Keep existing BC training and v1 actor inference architecture unchanged."""
    def __init__(self, recipe):
        nn.Module.__init__(self)
        self.encoder = Encoder(recipe)
        self.head = nn.Sequential(nn.Linear(128, 128), nn.ReLU(), nn.Linear(128, 12))

    def sample(self, observation, deterministic=False):
        mean, log_std = self.head(self.encoder(observation)).chunk(2, -1)
        distribution = torch.distributions.Normal(mean, log_std.clamp(-5., 2.).exp())
        raw = mean if deterministic else distribution.rsample()
        log_prob = (distribution.log_prob(raw) - 2*(math.log(2)-raw-F.softplus(-2*raw))).sum(-1, keepdim=True)
        return raw.tanh(), log_prob


class SAC:
    """RLPD-style backup: min target Q, no entropy in backup; mean Q actor loss.

    Timeout dones are masked by the replay sampler; successes disable bootstrap.
    The caller controls critic/actor update ratio, by default two to one.
    """
    def __init__(self, recipe, contract, *, device="cpu", learning_rate=3e-4,
                 gamma=.98, tau=.005, critic_actor_ratio=2, pretrained=None, image_augmentation=True):
        if recipe["encoder"] == "synthetic-test" and contract["config"]["transport"] != "fake":
            raise ValueError("synthetic encoder is forbidden for real observations")
        if not 0 <= gamma <= 1 or not 0 < tau <= 1 or critic_actor_ratio < 1:
            raise ValueError("invalid SAC hyperparameters")
        if recipe["encoder"] == "current9stack":
            from omi_hil_rl.training.eef_bc_grid import GridProfile
            if recipe["base_contract"] != GridProfile(contract["config"]["wrist_camera"]).CONTRACT:
                raise ValueError("encoder and transport base observation contracts disagree")
            if contract["config"]["transport"] == "ros" and recipe.get("sdk_convention") != contract["config"]["sdk_convention"]:
                raise ValueError("recipe and transport SDK conversions disagree")
        self.recipe, self.contract = deepcopy(recipe), deepcopy(contract)
        self.device = torch.device(device)
        encoder = Encoder(recipe)
        self.actor, self.critic = Actor(recipe, encoder), Critics(recipe, encoder)
        if pretrained is not None:
            encoder.initialize_pretrained(pretrained)
        self.actor.to(self.device).eval()
        self.critic.to(self.device).eval()
        self.target = deepcopy(self.critic).requires_grad_(False).eval()
        self.temperature_raw = nn.Parameter(torch.tensor(math.log(math.expm1(.01)), device=self.device))
        # Only the critic optimizer owns the shared fused encoder. The actor
        # detaches it; our fused proprio adapter differs from the reference's
        # separately trainable proprio branch. Standalone BC can still train it.
        self.actor_optimizer = torch.optim.Adam(self.actor.head.parameters(), lr=learning_rate)
        self.critic_optimizer = torch.optim.Adam([p for p in self.critic.parameters() if p.requires_grad], lr=learning_rate)
        self.alpha_optimizer = torch.optim.Adam([self.temperature_raw], lr=learning_rate)
        self.gamma, self.tau, self.ratio = gamma, tau, critic_actor_ratio
        self.image_augmentation = image_augmentation
        self.learning_rate, self.updates = learning_rate, 0

    def observation(self, obs, *, single=False):
        return {key: torch.as_tensor(value, device=self.device).unsqueeze(0) if single
                else torch.as_tensor(value, device=self.device) for key, value in obs.items()}

    @torch.inference_mode()
    def act(self, obs, deterministic=False):
        return self.actor.sample(self.observation(obs, single=True), deterministic)[0][0].cpu().numpy()

    @staticmethod
    def _optimize(optimizer, loss, parameters):
        if not torch.isfinite(loss):
            raise ValueError("nonfinite SAC loss")
        parameters = [p for p in parameters if p.requires_grad]
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(parameters, 5., error_if_nonfinite=True)
        optimizer.step()

    def update(self, batch):
        obs, nxt = self.observation(batch.observations), self.observation(batch.next_observations)
        if self.image_augmentation and self.recipe['encoder'] == 'current9stack':
            obs, nxt = augment_images(obs), augment_images(nxt)
        action = batch.actions.to(self.device)
        rewards, dones = batch.rewards.to(self.device), batch.dones.to(self.device)
        with torch.no_grad():
            next_action, next_log_prob = self.actor.sample(nxt)
            target = rewards + self.gamma * (1 - dones) * self.target(nxt, next_action).min(0).values
        critic_loss = (self.critic(obs, action) - target.unsqueeze(0)).square().mean()
        self._optimize(self.critic_optimizer, critic_loss, self.critic.parameters())
        self.updates += 1
        metrics = dict(update=self.updates, critic_loss=float(critic_loss.detach()), alpha=float(F.softplus(self.temperature_raw).detach()))
        if self.updates % self.ratio == 0:
            # Freeze critic parameters while retaining dQ/da for the actor.
            flags = [p.requires_grad for p in self.critic.parameters()]
            self.critic.requires_grad_(False)
            try:
                sampled, log_prob = self.actor.sample(obs, detach_encoder=True)
                actor_loss = (F.softplus(self.temperature_raw).detach() * log_prob - self.critic(obs, sampled).mean(0)).mean()
                self._optimize(self.actor_optimizer, actor_loss, self.actor.head.parameters())
            finally:
                for parameter, flag in zip(self.critic.parameters(), flags):
                    parameter.requires_grad_(flag)
            alpha_loss = F.softplus(self.temperature_raw) * (-next_log_prob.mean() + 3.)  # target entropy=-6/2
            self._optimize(self.alpha_optimizer, alpha_loss, [self.temperature_raw])
            metrics.update(actor_loss=float(actor_loss.detach()), alpha_loss=float(alpha_loss.detach()))
        with torch.no_grad():
            for target_param, param in zip(self.target.parameters(), self.critic.parameters()):
                target_param.lerp_(param, self.tau)
        return metrics

    def checkpoint(self):
        return dict(version=VERSION, recipe=self.recipe, contract=self.contract, updates=self.updates,
            hyperparameters=dict(learning_rate=self.learning_rate, gamma=self.gamma, tau=self.tau, critic_actor_ratio=self.ratio,
                                 image_augmentation=self.image_augmentation),
            actor=self.actor.state_dict(), critic=self.critic.state_dict(), target=self.target.state_dict(),
            temperature_raw=self.temperature_raw.detach(), actor_optimizer=self.actor_optimizer.state_dict(),
            critic_optimizer=self.critic_optimizer.state_dict(), alpha_optimizer=self.alpha_optimizer.state_dict(),
            torch_rng=torch.get_rng_state(),
            numpy_rng=[np.random.get_state()[0], np.random.get_state()[1].tolist(),
                       *np.random.get_state()[2:]],
            cuda_rng=torch.cuda.get_rng_state_all() if self.device.type == "cuda" else [])

    @classmethod
    def restore(cls, state, *, device="cpu", expected_contract=None):
        if state["version"] != VERSION or (expected_contract is not None and state["contract"] != expected_contract):
            raise ValueError("SAC checkpoint/contract mismatch; v1 requires a new v2 run, not --resume")
        for key, value in state['actor'].items():
            if key.startswith('encoder.') and not torch.equal(value, state['critic'][key]):
                raise ValueError('checkpoint shared encoder copies disagree')
        agent = cls(state["recipe"], state["contract"], device=device, **state["hyperparameters"])
        for name in ("actor", "critic", "target"):
            getattr(agent, name).load_state_dict(state[name], strict=True)
        with torch.no_grad():
            agent.temperature_raw.copy_(state["temperature_raw"])
        for name in ("actor_optimizer", "critic_optimizer", "alpha_optimizer"):
            getattr(agent, name).load_state_dict(state[name])
        agent.updates = state["updates"]
        torch.set_rng_state(state["torch_rng"].cpu())
        rng = state["numpy_rng"]
        np.random.set_state((rng[0], np.asarray(rng[1], dtype=np.uint32), *rng[2:]))
        if agent.device.type == "cuda" and state["cuda_rng"]:
            torch.cuda.set_rng_state_all([value.cpu() for value in state["cuda_rng"]])
        return agent


def load_actor(path, contract, device="cpu"):
    state = torch.load(path, map_location=device, weights_only=True)
    if state["version"] not in (VERSION, LEGACY_VERSION) or state["contract"] != contract:
        raise ValueError("actor checkpoint/observation/action contract mismatch")
    if state["recipe"]["encoder"] == "synthetic-test" and contract["config"]["transport"] != "fake":
        raise ValueError("synthetic encoder cannot control real hardware")
    actor_class = Actor if state['version'] == VERSION else LegacyActor
    actor = actor_class(state["recipe"]).to(device).eval()
    actor.load_state_dict(state["actor"], strict=True)
    return actor, state["updates"], state["recipe"]
