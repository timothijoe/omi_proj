# 2026-10-03：修复SDK无帧号六维力被省略

用户要求定位并解决wrench零消息。发布机domain13只读订阅6秒：A/B metadata170/164条，
wrench均0条，状态unframed_or_mismatched_omitted；运行配置enable_wrench=true。
确认省略发生在发布端，不是录包话题名错误。

短暂停止原双指触觉进程，保留腕部与其他进程，直接采样两指SDK各5次。
getForce实际返回(1,6) float32 ndarray，不带帧号；数值存在且变化。
旧适配仅接受(fid, six_values)，误把这一合法SDK格式过滤。

新增normalize_wrench，支持无帧号六向量，标记unframed_host_read_unsynchronized；
依然拒绝显式错帧、错误维数、NaN/Inf，不补零、不伪造SDK帧号。
WrenchStamped保留原话题和六分量顺序，时间为主机读取时间；metadata追加wrench_provenance，
明确source_frame_id=null、非同帧验证、无源时间、未验证新鲜度和标定单位/轴。
触觉三场同帧要求不变，六维力不宣称与三场同步。

恢复同domain13/network双指采集后，本地6秒接收A164条、B160条wrench，均有六个有限数值。
远端录包机尚未复验；旧包的零消息不可修复。未改raw发布，不控制机器人。
建议录包保留两指metadata/status以追溯语义与故障。未commit/push。
