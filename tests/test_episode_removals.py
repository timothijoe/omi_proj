import json

import pytest

from omi_hil_rl.hil.async_training import remaining_episode_budget


def test_removed_original_episodes_still_consume_cumulative_budget(tmp_path):
    session = dict(control_mode='periodic_training_v1', max_total_episodes=300)
    original = tmp_path/'periodic_episodes'/'kept'
    original.mkdir(parents=True)
    (original/'audit.json').write_text('{}')
    (original/'staging.json').write_text('{}')
    ledger = dict(schema='omi-episode-removals-v1', started_episode_ids=['removed', 'kept'])
    (tmp_path/'episode_removals.json').write_text(json.dumps(ledger))
    # Union counts a restored/existing ID once, not twice, and removal is not a refund.
    assert remaining_episode_budget(tmp_path, session, 300) == 298
    assert remaining_episode_budget(tmp_path, session, 5) == 5
    assert remaining_episode_budget(tmp_path, {}, 300) == 300


@pytest.mark.parametrize('ids', [None, 'removed', [None], ['a', 'a'], ['../bad']])
def test_invalid_removal_ledger_does_not_silently_increase_budget(tmp_path, ids):
    (tmp_path/'episode_removals.json').write_text(json.dumps(
        dict(schema='omi-episode-removals-v1', started_episode_ids=ids)))
    with pytest.raises(ValueError, match='removed-episode ledger'):
        remaining_episode_budget(tmp_path, dict(max_total_episodes=300), 300)
