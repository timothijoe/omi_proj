"""Policy candidate contract before the single gamepad/SDK output boundary."""
import math
import numpy as np
from .sdk_action import output_action

POLICY_FRAME = 'base_link'
SDK_CONVENTION = 'sdk-x-forward-z-left'
SDK_FROM_POLICY = np.array([[1.,0.,0.],[0.,0.,-1.],[0.,1.,0.]])


def policy_trace(action, scale=1., *, max_translation_m=None, max_rotation_rad=None):
    """Scale then independently cap dp/rotvec norms, before SDK conversion.

    Omitted limits retain the unbounded trace for offline analysis. The live
    producer supplies both limits; the arbiter independently checks the result.
    """
    if not math.isfinite(scale) or not 0 < scale <= 1:
        raise ValueError('Policy scale must be in (0, 1]')
    d=np.asarray(action,dtype=float)
    if d.shape != (6,) or not np.isfinite(d).all():
        raise ValueError('Expected finite six-dimensional policy action')
    scaled=d*scale
    selected=scaled.copy()
    factors=[]
    for part,limit in ((selected[:3],max_translation_m),(selected[3:],max_rotation_rad)):
        if limit is not None and (not math.isfinite(limit) or limit<=0):
            raise ValueError('Action norm limits must be finite and positive')
        norm=math.hypot(*part)
        factor=1. if limit is None or norm<=limit else limit/norm
        part*=factor
        factors.append(factor)
    return dict(network_action_m_rad=d.tolist(),network_original_mm_rotvec_deg=output_action(d,'legacy'),
                policy_scale=scale,candidate_m_rad=selected.tolist(),
                scaled_before_limit_m_rad=scaled.tolist(),
                scaled_before_limit_mm_rotvec_deg=output_action(scaled,'legacy'),
                translation_limit_scale=factors[0],rotation_limit_scale=factors[1],
                norm_limited=any(f<1 for f in factors),
                max_translation_m=max_translation_m,max_rotation_rad=max_rotation_rad,
                original_mm_rotvec_deg=output_action(selected,'legacy'),
                sdk_preview_mm_abc_deg=output_action(selected,SDK_CONVENTION),
                output_convention=SDK_CONVENTION,conversion_enabled=True,
                candidate_frame=POLICY_FRAME,candidate_is_sdk_converted=False)


def candidate_reason(status, now_ns, max_translation_m=.001, max_rotation_rad=math.pi/180):
    """Fail closed; same per-step norm limits as the gamepad arbiter."""
    if status.get('header_mode') != 'strict':return 'diagnostic_headers'
    if not status.get('inferred') or not status.get('finite'):return 'no_finite_prediction'
    if not status.get('within_experimental_bounds'):return 'experimental_bounds'
    mask=status.get('history_mask',[])
    if len(mask)!=10 or not all(mask):return 'history_warmup_or_gap'
    if not status['reference_ns'] <= now_ns < status['expires_ns']:return 'expired_or_future'
    action=np.asarray(status['policy_trace']['candidate_m_rad'])
    if np.linalg.norm(action[:3])>max_translation_m+1e-12:return 'policy_translation_speed_bound'
    if np.linalg.norm(action[3:])>max_rotation_rad+1e-12:return 'policy_rotation_speed_bound'
    return 'ok'
