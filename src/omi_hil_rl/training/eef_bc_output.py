"""Typed, shadow-only proposal construction. No robot publisher or executor."""
import numpy as np
from .eef_action import apply, check_increment
from .eef_bc_data import CONTRACT


def proposal_values(prediction, observation):
    action=check_increment(prediction,CONTRACT["max_translation_m"],CONTRACT["max_rotation_rad"])
    anchor=observation["state"][-7:]
    target=apply(anchor,action)
    return dict(action_delta=action.tolist(),anchor_pose=anchor.tolist(),proposed_pose=target.tolist(),
                semantics=CONTRACT["action"],frame_id=CONTRACT["frame_id"],
                action_version=CONTRACT["action_version"],source="POLICY",valid=True)


def message(row,decision_ns):
    from omi_action_msgs.msg import EefActionProposal
    m=EefActionProposal()
    def stamp(field,value):
        field.sec,field.nanosec=divmod(int(value),10**9)
    def pose(field,values):
        field.position.x,field.position.y,field.position.z=map(float,values[:3])
        field.orientation.x,field.orientation.y,field.orientation.z,field.orientation.w=map(float,values[3:])
    stamp(m.header.stamp,row["reference_ns"])
    stamp(m.decision_stamp,decision_ns)
    stamp(m.anchor_stamp,row["source_stamps"]["eef"])
    stamp(m.horizon,CONTRACT["label_horizon_ns"])
    m.header.frame_id=CONTRACT["frame_id"]
    m.epoch=row["epoch"]
    m.contract_version=CONTRACT["action_version"]
    m.source="POLICY"; m.action_type="BASE_EEF_DELTA_CURRENT_POSE"
    m.translation_unit="m"; m.rotation_unit="rad_rotvec"
    m.label_semantics=CONTRACT["action"]
    m.valid=True; m.shadow_only=True
    m.translation.x,m.translation.y,m.translation.z=map(float,row["action_delta"][:3])
    m.rotation_vector.x,m.rotation_vector.y,m.rotation_vector.z=map(float,row["action_delta"][3:])
    pose(m.anchor_pose,row["anchor_pose"]); pose(m.proposed_pose,row["proposed_pose"])
    return m
