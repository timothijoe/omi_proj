import numpy as np
from stable_baselines3 import SAC

from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv
from omi_hil_rl.training.demo_import import import_human_demonstrations
from omi_hil_rl.training.hil_replay import HILReplayBuffer
from omi_hil_rl.training.recording import TransitionRecorder


def test_recorded_human_action_can_seed_replay(tmp_path):
    path = tmp_path / "keyboard.jsonl"
    recorder = TransitionRecorder(TianjiSurrogateEnv(), path)
    recorder.reset(seed=0)
    recorder.step(np.zeros(7), intervention_active=True, human_action=np.ones(7))
    recorder.close()

    env = TianjiSurrogateEnv()
    try:
        model = SAC(
            "MultiInputPolicy", env, replay_buffer_class=HILReplayBuffer,
            replay_buffer_kwargs={"demo_fraction": 0.5}, buffer_size=100,
            policy_kwargs={"net_arch": [16, 16]}, learning_starts=1,
        )
        assert import_human_demonstrations(model, path, env.model_kind) == 1
        assert model.replay_buffer.size() == 1
        assert model.replay_buffer.human_mask[0]
        assert not model.replay_buffer.online_mask[0]
        assert np.allclose(model.replay_buffer.actions[0, 0], 1.0)
    finally:
        env.close()
