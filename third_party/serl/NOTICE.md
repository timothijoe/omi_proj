# SERL architecture reference

`src/omi_hil_rl/training/serl_resnet10.py` implements a PyTorch port of the
ResNet-10 architecture in `serl_launcher/vision/resnet_v1.py` from
https://github.com/rail-berkeley/hil-serl, reference commit
`c32939bccb65f3b8c43a9f9add3d322d4ab0264a`.

Upstream copyright: Jianlan Luo, Charles Xu, Jeffrey Wu (2024).
Upstream Apache-2.0 license is included in `LICENSE`.
Changes: PyTorch NCHW modules, explicit Flax SAME padding, numeric NPZ weight
conversion, fixed 128x128 input, omission of classifier/conditioning/pooling.

Pretrained weights are downloaded separately from
https://github.com/rail-berkeley/serl/releases/tag/resnet10 and stored under
Git-ignored `local/pretrained/serl_resnet10/`. They are not included in this repository.
