# 2026-10-17 控制响应证据

来源为用户现场录制的 `local/diagnostics/control_response/20261017_193243_851241.json`。原始文件不进入Git；SHA-256为 `e99b61c8f0e96501a0f6fe6a7e2108f8e9fe96f6fe9bcc6b863816663bca6403`，复制后应核对。

- [response.png](response.png)：指令X速度、反馈X位置/差分速度，以及四次全零后的衰减。
- [analysis.json](analysis.json)：阈值定义、四段结果、采样间隔、原始哈希、差分窗口敏感性及日志核查。
- [工作快照](../../oct17_development_checkpoint.md)：当前实现、结论、限制和待办。

在项目根目录用具备NumPy、Matplotlib和中文字体的解释器复现；本机为系统Python。输出到新的本地目录：

```bash
/usr/bin/python3 scripts/analyze_control_response.py \
  local/diagnostics/control_response/20261017_193243_851241.json \
  --output local/diagnostics/control_response/recheck_193243 \
  --receiver-log /home/zhoutong/.ros/log/python3_181314_1792236613237.log
```

没有原接收端日志时省略 `--receiver-log`，不能凭录制文件缺少告警行就推断无SDK错误。分析针对含完整前后X动作及归零段的记录；没有SDK目标或物理松手时间，阈值/波形偏移不是纯网络时延。
