import numpy as np
import pytest

from omi_hil_rl.hil.fit_all_bc import combine_splits, evaluate


def test_old_validation_explicitly_becomes_training():
    a = ({'x': np.ones((2, 3))}, np.zeros((2, 6)), ['a:0', 'a:1'])
    b = ({'x': np.zeros((1, 3))}, np.ones((1, 6)), ['b:0'])
    obs, labels, ids = combine_splits(dict(training=a, validation=b))
    assert obs['x'].shape == (3, 3)
    assert np.array_equal(labels[-1], b[1][0])
    assert ids == ['a:0', 'a:1', 'b:0']
    with pytest.raises(ValueError, match='duplicate'):
        combine_splits(dict(training=a, validation=a))


def test_per_episode_metrics_preserve_order():
    labels = np.zeros((3, 6))
    prediction = labels.copy()
    prediction[-1] = 1
    result = evaluate(prediction, labels, ['a:0', 'a:1', 'b:0'], np.ones(6))
    assert result['episodes']['a']['mse'] == 0
    assert result['episodes']['b']['mse'] == 1
    assert result['overall']['mse'] == pytest.approx(1/3)
