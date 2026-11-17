# AI 舆情本地服务

模块可独立运行。它使用本机已保存的日报，在服务启动时构建页面；手动点击才采集或发起模型分析。它不会创建定时任务。

在模块目录使用 Python 3.10+：

```sh
python3 bin/server.py --host 127.0.0.1 --port 0
```

终端第一行 JSON 的 `port` 是本机端口，在浏览器打开 `http://127.0.0.1:<port>/`。保持该进程运行。指定已有日报和单独的网页输出时：

```sh
python3 bin/server.py --data-dir ./data --site-dir ./site --config-dir "$WORKHUB_DATA_DIR"
```

默认模型配置目录为 `~/.local/share/agent-workhub`，与本机 Workhub 共用；也可用 `--config-dir` 指定包含 `llm.json` 的目录。没有 Workhub 时可自行创建同格式的私有配置文件（权限 `0600`）：

```json
{
  "provider": "glm",
  "model": "glm-5.3-flash",
  "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "api_keys": ["YOUR_API_KEY"]
}
```

请在本机私有文件中填入自己的凭据；不要把文件提交到仓库。除 GLM 外，该服务使用相同配置格式和提供方传输机制，支持 Workhub 已支持的 OpenAI 兼容 API、Anthropic、Ollama 及 CLI。CLI 包装器需接受 Workhub 的 `{system,evidence}` JSON 输入，并根据新闻提示返回本文定义的 JSON 输出；仅接受项目评议结构的专用包装器不一定兼容。每次点击分析才读取配置并调用提供方；页面读取状态不会触发调用。

发送给模型的是当前快照最多 80 个来源标题、来源名、时间和临时 ID、覆盖状态及截断统计；不发送原文全文、URL、本地文件或完整数据库。新闻均属未验证输入，提示词要求模型不得服从新闻中的指令，输出只允许引用本次已有 ID；这不能保证模型绝不受注入影响或保证结论属实。已配置 Key 从标题与来源字段中隐藏，含 Key 或敏感查询参数的链接不会显示。结果保存在本模块私有 `data/ai-analysis.json`，与快照 run_id 关联；数据更新后标识结果过期。模型分析不是事实核查，需查看原始来源。

`POST /api/collect` 和 `/api/analyze` 只能同源请求，要求 `Content-Type: application/json`、`X-Workhub-Request: 1`、有效 Origin，且请求体只能为 `{}`。`GET /api/state` 只读取状态。服务只监听 127.0.0.1，检查 Host；Workhub 安装器还可显式指定可信 `--parent-origin`，以允许内嵌。本地服务凭持有的 flock 独占同一数据目录；锁文件存在本身不表示进程仍在运行。安装器负责管理其自己启动的服务进程。
