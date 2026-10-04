"""Isolated actual ROS observation replay plus shadow-only BC inference.

Replay references carry source watermarks, NOT observations or target actions.
The learner must receive and decode the actual sensor topics before predicting.
Watermarks make DDS cross-topic arrival order testable, not a hardware sync claim.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .bag_bc_data import ARRAYS, CONTRACT, TOPICS, ObservationBuffer, NotReady, decode, digest, reader

NS = "/omi/shadow"


def profile_modules(name, contract=None):
    if name == "eef":
        from . import eef_bc_data as data, eef_bc_policy as policy
        if contract and contract.get('version') in ('bag-eef-bc-v3-grid-receive','bag-eef-bc-v4-wrench'):
            raise ValueError('Recorder-time grid profile is offline-only in this legacy adapter; use eef_history_online.sh for history checkpoints')
        return data.profile_for(data.CONTRACT if contract is None else contract), policy, "/omi/eef_shadow"
    if name == "joint":
        from . import bag_bc_data as data, bc_policy as policy
        return data, policy, NS
    raise ValueError("Unknown BC profile")


def validate_replay_topics(profile, manifest, actual):
    allowed = set(profile.TOPICS)
    required = set(getattr(profile, "REQUIRED_TOPICS", allowed))
    if not required <= actual <= allowed or actual != set(manifest.get("replay_topics", allowed)):
        raise ValueError("Replay topics differ from saved source contract or include non-observations")


def validate_isolation():
    if int(os.environ.get("ROS_DOMAIN_ID", "0")) == 0 or os.environ.get("ROS_LOCALHOST_ONLY") != "1":
        raise ValueError("Requires nonzero ROS domain and ROS_LOCALHOST_ONLY=1; use scripts/bag_bc.sh")


def replay(args):
    import rclpy
    from std_msgs.msg import String
    from rosidl_runtime_py.utilities import get_message
    validate_isolation()
    manifest = json.loads((args.dataset/"manifest.json").read_text())
    data_profile, policy_profile, namespace = profile_modules(args.profile, manifest["contract"])
    TOPICS = data_profile.TOPICS
    refs = json.loads((args.dataset/"references.json").read_text())
    rclpy.init()
    node = rclpy.create_node("bc_sensor_replay")
    control = node.create_publisher(String, namespace+"/reference", 64)
    ack = set()
    node.create_subscription(String, namespace+"/ack", lambda m: ack.add(m.data), 64)
    rd = reader(args.dataset/"observations")
    types = rd.get_all_topics_and_types()
    validate_replay_topics(data_profile, manifest, {t.name for t in types})
    pubs = {t.name: node.create_publisher(get_message(t.type), t.name, 64) for t in types}
    del rd

    def spin_until(deadline):
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=min(.01, max(0., deadline-time.monotonic())))

    def handshake(kind, epoch):
        key = f"{kind}:{epoch}"
        deadline = time.monotonic()+15
        while key not in ack:
            if time.monotonic() > deadline:
                raise TimeoutError("Inference acknowledgement missing: "+key)
            control.publish(String(data=json.dumps(dict(kind=kind, epoch=epoch))))
            spin_until(time.monotonic()+.1)

    try:
        deadline = time.monotonic()+15
        while any(p.get_subscription_count() == 0 for p in pubs.values()) or control.get_subscription_count() == 0:
            if time.monotonic()>deadline:
                raise TimeoutError("Missing inference subscribers")
            spin_until(time.monotonic()+.1)
        for epoch in range(args.loops):
            handshake("begin", epoch)
            rd = reader(args.dataset/"observations")
            event = rd.read_next() if rd.has_next() else None
            began, pause_added, paused = time.monotonic(), 0., False
            for ref in refs:
                offset = (ref["reference_ns"]-manifest["start_ns"])/1e9
                if args.pause_at >= 0 and offset >= args.pause_at and not paused:
                    spin_until(time.monotonic()+args.pause_seconds)
                    pause_added += args.pause_seconds
                    paused = True
                while event is not None and event[2] <= ref["reference_ns"]:
                    topic, payload, received = event
                    spin_until(began+(received-manifest["start_ns"])/1e9/args.rate+pause_added)
                    pubs[topic].publish(payload)  # original CDR, no actions or label stream
                    event = rd.read_next() if rd.has_next() else None
                spin_until(began+offset/args.rate+pause_added)
                control.publish(String(data=json.dumps(dict(kind="sample", epoch=epoch, **ref))))
                rclpy.spin_once(node, timeout_sec=0)
            del rd
            handshake("end", epoch)
            spin_until(time.monotonic()+.15)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def run(args):
    import rclpy
    from std_msgs.msg import String
    from rosidl_runtime_py.utilities import get_message
    manifest = json.loads((args.dataset/"manifest.json").read_text())
    data_profile, policy_profile, namespace = profile_modules(args.profile, manifest["contract"])
    ARRAYS = data_profile.ARRAYS
    CONTRACT, TOPICS = data_profile.CONTRACT, data_profile.TOPICS
    ObservationBuffer, decode, digest = data_profile.ObservationBuffer, data_profile.decode, data_profile.digest
    load_policy, predict = policy_profile.load_policy, policy_profile.predict
    is_eef = args.profile == "eef"
    validate_isolation()
    if args.output.exists():
        raise FileExistsError("Refuse to overwrite shadow report")
    manifest = json.loads((args.dataset/"manifest.json").read_text())
    if manifest["contract"] != CONTRACT:
        raise ValueError("Dataset contract mismatch")
    expected_per_epoch=sum(bool(r["valid"]) for r in json.loads((args.dataset/"references.json").read_text()))
    model, norm, checkpoint = load_policy(args.checkpoint)
    if checkpoint["contract"] != manifest["contract"]:
        raise ValueError("Dataset/checkpoint input-source contract mismatch")
    args.output.mkdir(parents=True)
    rclpy.init()
    node = rclpy.create_node("bc_shadow_inference")
    if is_eef:
        from omi_action_msgs.msg import EefActionProposal
        from .eef_bc_output import proposal_values, message as proposal_message
        action_pub = node.create_publisher(EefActionProposal, namespace+"/policy_proposal", 10)
    else:
        action_pub = node.create_publisher(String, NS+"/prediction", 10)
    status_pub = node.create_publisher(String, namespace+"/status", 10)
    ack_pub = node.create_publisher(String, namespace+"/ack", 64)
    buf, pending, records = ObservationBuffer(), deque(), []
    received, issues = Counter(), Counter()
    state = dict(epoch=-1, last_reference_wall=None, paused=False, ending=None, epochs_completed=0)
    errors = []
    typed_received = set()
    if is_eef:
        def verify_proposal(m):
            key=(int(m.epoch), int(m.header.stamp.sec)*10**9+int(m.header.stamp.nanosec))
            if (not m.shadow_only or not m.valid or m.header.frame_id != CONTRACT["frame_id"]
                    or m.contract_version != CONTRACT["action_version"] or m.source != "POLICY"):
                errors.append("Invalid typed shadow proposal metadata")
            expected = next((r for r in records if (r["epoch"], r["reference_ns"]) == key), None)
            wire_action = np.array([m.translation.x,m.translation.y,m.translation.z,
                                    m.rotation_vector.x,m.rotation_vector.y,m.rotation_vector.z])
            wire_pose = np.array([m.proposed_pose.position.x,m.proposed_pose.position.y,m.proposed_pose.position.z,
                                  m.proposed_pose.orientation.x,m.proposed_pose.orientation.y,
                                  m.proposed_pose.orientation.z,m.proposed_pose.orientation.w])
            if (expected is None or not np.array_equal(wire_action, expected["action_delta"])
                    or not np.array_equal(wire_pose, expected["proposed_pose"])
                    or m.translation_unit != "m" or m.rotation_unit != "rad_rotvec"):
                errors.append("Typed shadow payload differs from policy proposal")
            typed_received.add(key)
        node.create_subscription(EefActionProposal, namespace+"/policy_proposal", verify_proposal, 64)
    rd = reader(args.dataset/"observations")
    types = rd.get_all_topics_and_types()
    del rd
    validate_replay_topics(data_profile, manifest, {t.name for t in types})

    def receive(key, message):
        if state["epoch"] < 0:
            return
        try:
            buf.add(key, *decode(key, message))
            received[key] += 1
        except ValueError as exc:
            errors.append(key+":"+str(exc))
            buf.clear()  # fail closed; do not predict from a mixed temporal epoch

    for meta in types:
        key=TOPICS[meta.name]
        node.create_subscription(get_message(meta.type), meta.name, lambda m,k=key: receive(k,m), 64)

    def reference(msg):
        ref=json.loads(msg.data)
        epoch=ref["epoch"]
        if ref["kind"] == "begin":
            if epoch != state["epoch"]:
                buf.clear()
                pending.clear()
                state.update(epoch=epoch, last_reference_wall=None, paused=False, ending=None)
                issues["explicit_epoch_resets"] += 1
            ack_pub.publish(String(data=f"begin:{epoch}"))
        elif epoch != state["epoch"]:
            issues["wrong_epoch_reference"] += 1
        elif ref["kind"] == "end":
            state["ending"] = epoch
        elif ref["kind"] == "sample":
            state["last_reference_wall"] = time.monotonic()
            state["paused"] = False
            if not ref["valid"]:
                issues["source_rejected:"+ref["reason"]] += 1
                status_pub.publish(String(data=json.dumps(dict(state="NOT_READY", epoch=epoch, reason=ref["reason"], reference_ns=ref["reference_ns"]))))
            elif len(pending) >= 32:
                issues["queue_overflow"] += 1
            else:
                pending.append((ref, time.monotonic()))
    node.create_subscription(String, namespace+"/reference", reference, 64)

    def tick():
        now=time.monotonic()
        wall=state["last_reference_wall"]
        if wall is not None and now-wall > .5 and not state["paused"]:
            state["paused"] = True
            issues["pause_or_end_detected"] += 1
            status_pub.publish(String(data=json.dumps(dict(state="STALE_OR_PAUSED", epoch=state["epoch"]))))
        if pending:
            ref, queued=pending[0]
            try:
                observation, stamps=buf.at(ref["reference_ns"], ref["source_stamps"])
            except NotReady:
                if now-queued > 1.:
                    pending.popleft()
                    issues["transport_timeout"] += 1
                return
            pending.popleft()
            if wall is None or now-wall > .5:
                issues["stale_reference_rejected"] += 1
                return
            if digest(observation) != ref["observation_sha256"]:
                errors.append("offline/ROS observation mismatch")
                return
            t=time.perf_counter()
            pred=predict(model, norm, {k:observation[k][None] for k in ARRAYS})[0]
            cost=(time.perf_counter()-t)*1000
            if pred.shape != ((6,) if is_eef else (7,)) or not np.isfinite(pred).all():
                errors.append("Invalid policy output")
                return
            row=dict(epoch=ref["epoch"], reference_ns=ref["reference_ns"], source_stamps=stamps,
                     action_target_rad=pred.tolist(), inference_ms=cost,
                     transport_wait_ms=(now-queued)*1000, input_exact_match=True,
                     shadow_only=True, semantics="assumed left absolute target, not a robot command")
            if is_eef:
                row.pop("action_target_rad")
                try:
                    row.update(proposal_values(pred, observation))
                except ValueError as exc:
                    issues["prediction_rejected:"+str(exc)] += 1
                    status_pub.publish(String(data=json.dumps(dict(state="PREDICTION_REJECTED", reason=str(exc),
                        epoch=ref["epoch"], reference_ns=ref["reference_ns"], shadow_only=True))))
                    return
                if "camera_mask" in observation:
                    row["camera_mask"] = observation["camera_mask"].tolist()
                    row["wrist_camera"] = CONTRACT["wrist_camera"]
                row["decision_ns"] = node.get_clock().now().nanoseconds
                action_pub.publish(proposal_message(row, row["decision_ns"]))
            else:
                action_pub.publish(String(data=json.dumps(row)))
            records.append(row)
        if state["ending"] is not None and not pending:
            epoch=state["ending"]
            ack_pub.publish(String(data=f"end:{epoch}"))
            state["epochs_completed"]=max(state["epochs_completed"],epoch+1)
    node.create_timer(.02, tick)
    command=[sys.executable,"-m","omi_hil_rl.training.bc_shadow","--worker-replay","--dataset",str(args.dataset.resolve()),
             "--profile",args.profile,"--loops",str(args.loops),"--rate",str(args.rate),"--pause-at",str(args.pause_at),"--pause-seconds",str(args.pause_seconds)]
    process=None
    topics=[]
    try:
        with (args.output/"replay.log").open("w") as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+args.loops*((manifest["end_ns"]-manifest["start_ns"])/1e9/args.rate+args.pause_seconds+10)+30
            while process.poll() is None:
                if time.monotonic()>deadline:
                    raise TimeoutError("Shadow run timeout")
                rclpy.spin_once(node,timeout_sec=.05)
                if errors:
                    raise RuntimeError(errors[-1])
                topics=[name for name,_ in node.get_topic_names_and_types()]
                if any(name.startswith('/tj/control/') for name in topics):
                    raise RuntimeError("Control topic detected in isolated test domain")
            if is_eef:
                drain_deadline=time.monotonic()+2
                while len(typed_received)<len(records) and time.monotonic()<drain_deadline:
                    rclpy.spin_once(node,timeout_sec=.02)
            if process.returncode:
                raise RuntimeError("Replay failed; inspect replay.log")
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        node.destroy_node()
        rclpy.shutdown()
        (args.output/"predictions.jsonl").write_text("".join(json.dumps(x)+"\n" for x in records))
        report=dict(predictions=len(records), received=dict(received), issues=dict(issues), errors=errors,
                    expected_predictions_per_epoch=expected_per_epoch,
                    epochs_completed=state["epochs_completed"], requested_loops=args.loops,
                    no_control_topics=not any(t.startswith('/tj/control/') for t in topics),
                    observed_topics=topics, checkpoint_mode=checkpoint["mode"],
                    input_parity="SHA256 of offline and ROS-built tensors, checked before each output")
        report["profile"]=args.profile
        if is_eef:
            report["typed_proposals_received"]=len(typed_received)
            report["action_contract"]=CONTRACT
            if "wrist_camera" in CONTRACT:
                report["camera_mask_counts"]=dict(Counter(
                    ",".join(str(int(x)) for x in r["camera_mask"]) for r in records))
        if records:
            report["inference_ms_p50_p95_max"]=np.percentile([r["inference_ms"] for r in records],[50,95,100]).tolist()
            report["transport_wait_ms_p50_p95_max"]=np.percentile([r["transport_wait_ms"] for r in records],[50,95,100]).tolist()
            with np.load(args.dataset/"samples.npz",allow_pickle=False) as data:
                labels={int(t):a for t,a in zip(data["reference_ns"],data["action"])}
                residual=[np.asarray(r["action_delta" if is_eef else "action_target_rad"])-labels[r["reference_ns"]] for r in records if r["reference_ns"] in labels]
                if is_eef and residual:
                    residual=np.asarray(residual)
                    report["proxy_translation_rmse_m"]=float(np.sqrt(np.mean(residual[:,:3]**2)))
                    report["proxy_rotation_rmse_rad"]=float(np.sqrt(np.mean(residual[:,3:]**2)))
                elif not is_eef:
                    report["recorded_target_rmse_rad"]=float(np.sqrt(np.mean(np.square(residual)))) if residual else None
            report["per_epoch_predictions"]={str(i):sum(r["epoch"]==i for r in records) for i in range(args.loops)}
        (args.output/"report.json").write_text(json.dumps(report,indent=2))
    if ((is_eef and len(typed_received)!=len(records)) or not records or state["epochs_completed"] != args.loops or errors or issues["transport_timeout"] or issues["queue_overflow"]
            or any(sum(r["epoch"]==i for r in records) != expected_per_epoch for i in range(args.loops))):
        raise RuntimeError("Incomplete shadow acceptance; inspect report.json")
    print(json.dumps(report,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile",choices=("joint","eef"),default="joint")
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--checkpoint",type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--loops",type=int,default=2)
    p.add_argument("--rate",type=float,default=1.)
    p.add_argument("--pause-at",type=float,default=6.)
    p.add_argument("--pause-seconds",type=float,default=1.)
    p.add_argument("--worker-replay",action="store_true",help=argparse.SUPPRESS)
    a=p.parse_args()
    if a.loops<1 or not np.isfinite(a.rate) or a.rate<=0 or not np.isfinite(a.pause_seconds) or a.pause_seconds<0:
        p.error("Invalid loop/rate/pause")
    if a.worker_replay:
        replay(a)
    else:
        if a.checkpoint is None or a.output is None:
            p.error("--checkpoint and --output required")
        run(a)


if __name__ == "__main__":
    main()
