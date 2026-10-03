# Experimental candidate; never a controller command.
# header stamp = historical reference observation time; frame_id = base_link.
std_msgs/Header header
builtin_interfaces/Time decision_stamp
builtin_interfaces/Time anchor_stamp
# Nominal future horizon from header.stamp, not from anchor_stamp.
builtin_interfaces/Duration horizon
uint32 epoch
string contract_version
string source
string action_type
string translation_unit
string rotation_unit
string label_semantics
bool valid
bool shadow_only
string rejection_reason
# Base-axis position difference and left-multiplied principal rotation vector.
geometry_msgs/Vector3 translation
geometry_msgs/Vector3 rotation_vector
geometry_msgs/Pose anchor_pose
geometry_msgs/Pose proposed_pose
