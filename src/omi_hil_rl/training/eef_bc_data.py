"""Causal multimodal data with explicitly acknowledged future-EEF proxy labels."""
from __future__ import annotations
import argparse
from bisect import bisect_left
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import tempfile
import numpy as np
from . import bag_bc_data as legacy
from . import eef_action

ARRAYS = legacy.ARRAYS
TOPICS = {**legacy.TOPICS, "/tj/info/eef_left": "eef"}
KEYS = tuple(TOPICS.values())
NotReady = legacy.NotReady
digest, reader, sha256 = legacy.digest, legacy.reader, legacy.sha256
CONTRACT = {**legacy.CONTRACT,
    "version": "bag-eef-bc-v1", "action_version": eef_action.VERSION,
    "state_shape": [26], "action_shape": [6],
    "state_order": "q_left_7,a_wrench_Fxyz_Txyz,b_wrench_Fxyz_Txyz,eef_xyz_xyzw",
    "action": "future_recorded_eef_change_proxy_not_control_command",
    "frame_id": "base_link", "anchor": "latest_causal_recorded_eef",
    "translation": "p_future-p_current; meters; base_axes",
    "rotation": "Log(R_future R_current^T); radians; base_axes; left_multiply",
    "quaternion": "xyzw; normalized_within_1e-3; canonical_sign_w_then_largest_xyz",
    "pose_semantics": "producer_FK_feedback_or_target_unknown; TCP_unverified",
    "eef_max_age_ns": 50_000_000, "max_pose_gap_ns": 50_000_000,
    "label_tolerance_ns": 20_000_000,
    "max_translation_m": .05, "max_rotation_rad": .25,
    "bounds": "experimental_reject_only; not_hardware_safety_limits",
    "deployment": "shadow_only; no_IK_no_hardware_command"}


def decode(key, message):
    if key != "eef":
        return legacy.decode(key,message)
    if message.header.frame_id != CONTRACT["frame_id"]:
        raise ValueError("EEF frame mismatch")
    p,q=message.pose.position,message.pose.orientation
    return legacy.stamp(message), eef_action.pose([p.x,p.y,p.z,q.x,q.y,q.z,q.w])


class ObservationBuffer(legacy.ObservationBuffer):
    def clear(self):
        super().clear()
        self.eef=deque(maxlen=128)

    def add(self,key,timestamp,value):
        if key != "eef":
            return super().add(key,timestamp,value)
        value=eef_action.pose(value)
        if timestamp <= 0 or (self.eef and timestamp < self.eef[-1][0]):
            raise ValueError("Invalid/backward EEF source header; reset required")
        if self.eef and timestamp == self.eef[-1][0]:
            self.eef.pop()
        self.eef.append((int(timestamp),value))

    def at(self,reference,expected=None):
        obs,stamps=super().at(reference,expected)
        wanted=None if expected is None else expected["eef"]
        item=next((x for x in reversed(self.eef) if x[0]<=reference and (wanted is None or x[0]==wanted)),None)
        if item is None:
            raise NotReady("missing:eef")
        if reference-item[0] > CONTRACT["eef_max_age_ns"]:
            raise NotReady("stale:eef")
        obs["state"]=np.r_[obs["state"],item[1]].astype(np.float32)
        stamps["eef"]=item[0]
        return obs,stamps


def label_for(reference,current_stamp,current_pose,pose_stamps,poses):
    desired=reference+CONTRACT["label_horizon_ns"]
    i=bisect_left(pose_stamps,desired)
    if i==len(poses) or pose_stamps[i]-desired>CONTRACT["label_tolerance_ns"]:
        raise NotReady("missing_future_eef")
    j=bisect_left(pose_stamps,current_stamp)
    if j==len(poses) or pose_stamps[j]!=current_stamp:
        raise NotReady("missing_anchor_eef")
    if np.any(np.diff(pose_stamps[j:i+1])>CONTRACT["max_pose_gap_ns"]):
        raise NotReady("eef_time_gap")
    action=eef_action.between(current_pose,poses[i])
    try:
        eef_action.check_increment(action,CONTRACT["max_translation_m"],CONTRACT["max_rotation_rad"])
    except ValueError as exc:
        raise NotReady(str(exc)) from exc
    return action,poses[i],pose_stamps[i]


def distribution(values):
    a=np.asarray(values)
    return dict(min=float(a.min()),p50=float(np.median(a)),p95=float(np.percentile(a,95)),max=float(a.max()))


def profile_for(contract):
    """Resolve an exact saved observation contract, preserving the v1 profile."""
    if contract == CONTRACT:
        import sys
        return sys.modules[__name__]
    from .eef_bc_sources import CameraProfile
    profile = CameraProfile(contract.get("wrist_camera"))
    if contract != profile.CONTRACT:
        raise ValueError("Unknown or modified EEF observation contract")
    return profile


def write_selected_replay(source, output, selected):
    """Copy original CDR only for source frames used by valid decision points.

    Selection is by original (topic, received_ns), never by re-encoding images.
    Source stamps and decoder behavior therefore stay identical to offline data.
    """
    import rosbag2_py
    rd = reader(source)
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(output), storage_id="mcap"),
                rosbag2_py.ConverterOptions("cdr", "cdr"))
    for meta in rd.get_all_topics_and_types():
        writer.create_topic(meta)
    copied = set()
    while rd.has_next():
        topic, payload, received = rd.read_next()
        if (topic, received) in selected:
            writer.write(topic, payload, received)
            copied.add((topic, received))
    del writer
    del rd
    if copied != selected:
        raise ValueError("Selected source frame missing from replay cache")
    return dict(Counter(topic for topic, _ in copied))


def export(source,output,*,accept_proxy=False,wrist_camera=None):
    if not accept_proxy:
        raise ValueError("Explicit --accept-future-state-proxy required")
    if wrist_camera is None:
        profile = profile_for(CONTRACT)
    else:
        from .eef_bc_sources import CameraProfile
        profile = CameraProfile(wrist_camera)
    contract, topics, keys = profile.CONTRACT, profile.TOPICS, profile.KEYS
    arrays_keys = profile.ARRAYS
    required_topics = set(getattr(profile, "REQUIRED_TOPICS", topics))
    selected_replay = contract["version"] == "bag-eef-bc-v2"
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    output=Path(output).resolve()
    if output.exists():
        raise FileExistsError("Refuse to overwrite dataset")
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eef-export-",dir=output.parent) as work:
        work=Path(work); build=work/"dataset"; build.mkdir()
        with legacy.open_bag(source,work) as (info,paths,provenance):
            start=int(info["starting_time"]["nanoseconds_since_epoch"])
            end=start+int(info["duration"]["nanoseconds"])
            if end<=start:
                raise ValueError("Empty bag")
            buf=profile.ObservationBuffer(); samples=[]; refs=[]; poses=[]; pose_stamps=[]
            counts,dropped=Counter(),Counter(); episode_hash=hashlib.sha256()
            ref,previous=start,start
            raw_replay = work/"all_observations" if selected_replay else build/"observations"
            source_receptions = {k: {} for k in keys}
            topic_for_key = {value: name for name, value in topics.items()}
            selected_events = set()
            writer=rosbag2_py.SequentialWriter()
            writer.open(rosbag2_py.StorageOptions(uri=str(raw_replay),storage_id="mcap"),rosbag2_py.ConverterOptions("cdr","cdr"))
            registered=set(); delays={k:[] for k in keys}
            def capture(t):
                row=dict(reference_ns=t)
                try:
                    obs,stamps=buf.at(t)
                    samples.append((t,obs,stamps))
                    if selected_replay:
                        selected_events.update((topic_for_key[key], source_receptions[key][timestamp])
                                               for key, timestamp in stamps.items() if timestamp > 0)
                    if "camera_mask" in obs:
                        row["camera_mask"] = obs["camera_mask"].tolist()
                    row.update(valid=True,source_stamps=stamps,observation_sha256=profile.digest(obs))
                except NotReady as exc:
                    dropped[str(exc)]+=1
                    row.update(valid=False,reason=str(exc))
                refs.append(row)
            for path in paths:
                rd=reader(path)
                types={t.name:t for t in rd.get_all_topics_and_types() if t.name in topics}
                classes={name:get_message(meta.type) for name,meta in types.items()}
                rd.set_filter(rosbag2_py.StorageFilter(topics=list(classes)))
                for name,meta in types.items():
                    if name not in registered:
                        writer.create_topic(meta); registered.add(name)
                while rd.has_next():
                    topic,data,received=rd.read_next()
                    if received<previous:
                        raise ValueError("Bag reception time goes backwards")
                    previous=received
                    while ref<received:
                        capture(ref); ref+=CONTRACT["label_horizon_ns"]
                    key=topics[topic]
                    timestamp,value=profile.decode(key,deserialize_message(data,classes[topic]))
                    if timestamp>received:
                        raise ValueError("Header later than reception; investigate clocks")
                    buf.add(key,timestamp,value)
                    if selected_replay:
                        source_receptions[key][timestamp] = received
                    if key=="eef":
                        if pose_stamps and timestamp==pose_stamps[-1]:
                            raise ValueError("Duplicate EEF timestamp is ambiguous")
                        pose_stamps.append(timestamp); poses.append(value)
                    counts[topic]+=1; delays[key].append((received-timestamp)/1e6)
                    if topic in TOPICS:
                        episode_hash.update(topic.encode()+b"\0"+str(received).encode()+b"\0"+data)
                    writer.write(topic,data,received)
                del rd
            while ref<=end:
                capture(ref); ref+=CONTRACT["label_horizon_ns"]
            del writer
            if not required_topics <= registered:
                raise ValueError("Required topics missing: "+str(required_topics-registered))
            replay_counts = (write_selected_replay(raw_replay, build/"observations", selected_events)
                             if selected_replay else dict(counts))
            rows=[]; labels=[]; targets=[]; label_stamps=[]; residual=[]
            for t,obs,stamps in samples:
                try:
                    action,target,label_stamp=label_for(t,stamps["eef"],obs["state"][-7:],pose_stamps,poses)
                except NotReady as exc:
                    dropped[str(exc)]+=1; continue
                restored=eef_action.apply(obs["state"][-7:],action)
                residual.append(eef_action.between(restored,target))
                rows.append((t,obs,stamps)); labels.append(action); targets.append(target); label_stamps.append(label_stamp)
            if len(rows)<2:
                raise ValueError("Too few valid samples")
            arrays={k:np.stack([r[1][k] for r in rows]) for k in arrays_keys}
            arrays.update(action=np.asarray(labels,dtype=np.float32),target_pose=np.asarray(targets),
                          reference_ns=np.array([r[0] for r in rows],dtype=np.int64),
                          label_ns=np.array(label_stamps,dtype=np.int64),
                          source_ns=np.array([[r[2][k] for k in keys] for r in rows],dtype=np.int64))
            arrays["actual_horizon_ns"]=arrays["label_ns"]-arrays["source_ns"][:,keys.index("eef")]
            np.savez_compressed(build/"samples.npz",**arrays)
            (build/"references.json").write_text(json.dumps(refs))
            a=arrays["action"]; r=np.asarray(residual)
            report=dict(contract=contract,source=provenance,episode_id=episode_hash.hexdigest(),
                interpretation="future state change proxy; one bag one episode; outcome unknown",
                start_ns=start,end_ns=end,input_counts=dict(counts),dropped=dict(dropped),
                replay_mode="selected_causal_source_frames" if selected_replay else "all_observation_messages",
                replay_counts=replay_counts,
                samples=len(rows),reference_count=len(refs),valid_observations=len(samples),source_order=list(keys),replay_topics=sorted(registered),
                translation_norm_m=distribution(np.linalg.norm(a[:,:3],axis=1)),
                rotation_norm_rad=distribution(np.linalg.norm(a[:,3:],axis=1)),
                actual_horizon_ms=distribution(arrays["actual_horizon_ns"]/1e6),
                source_to_receive_ms={k:distribution(v) if v else None for k,v in delays.items()},
                eef_source_interval_ms=distribution(np.diff(pose_stamps)/1e6),
                reconstruction_max_translation_m=float(np.linalg.norm(r[:,:3],axis=1).max()),
                reconstruction_max_rotation_rad=float(np.linalg.norm(r[:,3:],axis=1).max()),
                hold_translation_rmse_m=float(np.sqrt(np.mean(a[:,:3]**2))),
                hold_rotation_rmse_rad=float(np.sqrt(np.mean(a[:,3:]**2))),
                samples_sha256=sha256(build/"samples.npz"))
            if "camera_mask" in arrays:
                report["camera_mask_counts"] = dict(Counter(
                    ",".join(str(int(x)) for x in row) for row in arrays["camera_mask"]))
            (build/"manifest.json").write_text(json.dumps(report,indent=2))
        build.rename(output)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--accept-future-state-proxy",action="store_true")
    p.add_argument("--wrist-camera",choices=("off","required","optional"),default=None,
                   help="Select v2 camera profile; omitted preserves v1 single-camera export")
    a=p.parse_args()
    print(json.dumps(export(a.source,a.output,accept_proxy=a.accept_future_state_proxy,
                            wrist_camera=a.wrist_camera),indent=2))

if __name__=="__main__":
    main()
