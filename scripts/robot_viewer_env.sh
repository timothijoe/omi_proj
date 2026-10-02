# Sourced by the opt-in robot viewer; does not initialize ROS or connect devices.
# Local file is trusted shell configuration. Environment overrides take priority.
omi_viewer_root="$1"
omi_viewer_config="${OMI_ROBOT_VIEWER_CONFIG:-$omi_viewer_root/local/robot_state/viewer.env}"
omi_viewer_marvin_setup=""
omi_viewer_sdk_root="$omi_viewer_root/local/vendor/daimon_tactile"
if [[ -f "$omi_viewer_config" ]]; then
    source "$omi_viewer_config"
elif [[ -n "${OMI_ROBOT_VIEWER_CONFIG:-}" ]]; then
    echo "Missing viewer configuration: $omi_viewer_config" >&2
    return 1
fi
export OMI_MARVIN_MSGS_SETUP="${OMI_MARVIN_MSGS_SETUP:-$omi_viewer_marvin_setup}"
export OMI_DAIMON_SDK_ROOT="${OMI_DAIMON_SDK_ROOT:-$omi_viewer_sdk_root}"
unset omi_viewer_root omi_viewer_config omi_viewer_marvin_setup omi_viewer_sdk_root
