import json

from omi_hil_rl.hil.bc_wrench_monitor import BCWrenchMonitor
from omi_hil_rl.hil.bc_rollout import FixedBCActor
from omi_hil_rl.hil.watch_bc_wrench import live_status


def stable_samples(monitor, start, values):
    for i in range(20):
        when = start - .57 + i * .03
        for side in ('a', 'b'):
            monitor.ingest(side, values[side], when)


def test_start_baseline_and_warning_are_read_only(tmp_path):
    warnings = []
    monitor = BCWrenchMonitor(emit=warnings.append)
    values = {'a': (0., 0., -4., 0., 0., 0.),
              'b': (0., 0., -6., 0., 0., 0.)}
    stable_samples(monitor, 10., values)
    status = monitor.begin('episode-1', 10.)
    assert status['status'] == 'monitoring'
    assert status['baseline']['a'][2] == -4.
    monitor.ingest('a', (1.6, 0., -4., 0., 0., 0.), 10.1)
    monitor.ingest('b', (0., 0., -6., 0., .41, 0.), 10.2)
    monitor.ingest('b', (0.,) * 6, 10.3)
    result = monitor.finish('episode-1')
    assert [event['side'] for event in warnings] == ['a', 'b']
    assert result['exceeded_samples'] == {'a': 1, 'b': 1}
    assert result['invalid_samples']['b'] == 1
    assert result['action_effect'] == result['label_effect'] == 'none'
    assert monitor.active is None

    # A later Start uses a fresh baseline; the prior episode never changes it.
    values['a'] = (0., 0., -5., 0., 0., 0.)
    stable_samples(monitor, 12., values)
    assert monitor.begin('episode-2', 12.)['baseline']['a'][2] == -5.


def test_missing_or_unstable_prestart_data_never_becomes_baseline():
    monitor = BCWrenchMonitor()
    assert monitor.begin('missing', 10.)['status'] == 'baseline_unavailable'
    for i in range(20):
        now = 10. - .57 + i * .03
        for side in ('a', 'b'):
            monitor.ingest(side, (float(i % 2) * 2, 0., -4., 0., 0., 0.), now)
    status = monitor.begin('unstable', 10.)
    assert status['status'] == 'baseline_unavailable'
    assert 'unstable' in status['reason']
    assert monitor.active is None


def test_all_zero_finger_stream_is_not_accepted_as_stable_baseline():
    monitor = BCWrenchMonitor()
    stable_samples(monitor, 10.,
                   {'a': (0., 0., -4., 0., 0., 0.), 'b': (0.,) * 6})
    status = monitor.begin('zero-b', 10.)
    assert status['status'] == 'baseline_unavailable'
    assert status['reason'].startswith('b: all-zero')


def test_read_only_watch_reports_baseline_deltas_and_zero_stream():
    monitor = BCWrenchMonitor()
    stable_samples(monitor, 10.,
                   {'a': (0., 0., -4., 0., 0., 0.), 'b': (0., 0., -6., 0., 0., 0.)})
    assert monitor.begin('watch', 10.)['status'] == 'monitoring'
    monitor.ingest('a', (1., 0., -4., 0., .2, 0.), 10.1)
    monitor.ingest('b', (0.,) * 6, 10.1)
    status = live_status(monitor, 10.1)
    assert status['a']['delta_force_xy'] == 1.
    assert status['a']['delta_torque'] == .2
    assert status['b']['state'] == 'ALL_ZERO'


def test_bc_actor_saves_monitor_summary_without_changing_episode_state(tmp_path, capsys):
    episode = 'example'
    (tmp_path/'periodic_episodes'/episode).mkdir(parents=True)
    actor = object.__new__(FixedBCActor)
    actor.run = tmp_path
    actor.wrench_monitor = BCWrenchMonitor()
    stable_samples(actor.wrench_monitor, 10.,
                   {'a': (0., 0., -4., 0., 0., 0.), 'b': (0., 0., -6., 0., 0., 0.)})
    actor.periodic_monitor_start(episode, 10.)
    actor.wrench_monitor.ingest('a', (1.6, 0., -4., 0., 0., 0.), 10.1)
    actor.periodic_monitor_end(episode)
    result = json.loads((tmp_path/'periodic_episodes'/episode/'wrench_monitor.json').read_text())
    assert result['peaks']['a']['force_xy'] == 1.6
    assert result['action_effect'] == result['label_effect'] == 'none'
    assert 'BC_WRENCH_BASELINE' in capsys.readouterr().out
