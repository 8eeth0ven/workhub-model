[简体中文](collector.md) | [English](collector.en.md)

# 采集与日报

采集器只收公开新闻标题、原始链接和来源信息，不抓新闻全文，也不需要模型密钥。Python 3.10 或更新版本即可运行，不依赖 curl 或第三方包。

从模块目录执行：

```sh
python3 bin/collect.py --demo --data-dir /path/to/demo-data
python3 bin/collect.py --data-dir /path/to/auto-opinion-data
```

第一条仅生成明确标注的虚构示例，完全不联网。第二条才请求公开信息源。`--data-dir` 默认是模块内的 `data/`；它属于运行数据，不随模块发布。

演示和真实采集必须使用不同的数据目录。采集器会检查现有快照和目录模式，双向拒绝混用；演示不能覆盖真实日报，真实采集也不能把演示条目当作旧数据保留。仅有旧式 Markdown、无法确认模式的目录也会拒绝写入。上面两条命令因此刻意使用不同的 `--data-dir`。若已在默认 `data/` 体验演示，请为真实采集另选目录，并给看板构建器传入同一个新目录。

## 信息源与网络

默认共 13 个源：Google News RSS 的 10 组查询（理想专项 3 组、国内车企 4 组、国际车圈 3 组），以及 Electrek、Carscoops、百度汽车相关热搜。Google News、第三方 RSS 与百度接口的可用性由其服务和用户网络决定，本模块不保证每次可达。

默认直接连接，不读取环境中的代理变量。国际源可以通过私有配置的 `proxy` 或命令行 `--proxy` 显式设置 HTTP(S) 代理；百度热搜始终直连。代理故障默认不悄悄改走直连，只有显式设置 `proxy_fallback_direct: true` 才启用回退。配置文件和错误摘要不应公开真实代理地址。

复制 `config.example.json` 到发布目录之外的私有位置后修改，再运行：

```sh
python3 bin/collect.py --config /path/to/private-config.json --data-dir /path/to/auto-opinion-data
```

配置包含时间窗、时区、并发数、单次请求超时、重试次数和每源条目上限。`enabled_sources` 可选填源 ID 列表；Google 源 ID 为 `google-01` 至 `google-10`，其他是 `electrek`、`carscoops`、`baidu`。临时诊断可用 `--source electrek --source baidu --timeout 5 --retries 0`。最多并发 8 个源，默认 4 个；重试只针对超时、网络错误、空响应与部分临时 HTTP 错误，默认重试 1 次。响应体有大小限制，源失败不会取消其他源。

## 时间、去重与风险线索

RSS 条目要求可解析且带时区的发布日期，默认只收 UTC 时间精确过去 72 小时内的标题。未知日期、未来日期和窗外日期分别计数后拒收，不把解析失败当作“今天”。百度实时热搜缺乏可信发布日期，因此 `published_at` 为 `null`，另记 `observed_at` 与 `time_basis: observed`，不把观察时间冒充新闻发布时间。

全源按归一化标题确定性去重；这里只合并相同标题，不声称识别所有同题报道。标题按高风险、中风险、正向和普通四类关键词标记；英文词使用边界匹配，避免把 `firewall` 当作 `fire`。这些标签仅为待核实线索，不等于事件属实、法律判断或完整情绪分析。即使未命中，也要人工复核理想专项及来源覆盖。

## 输出与故障处理

每份 JSON 使用 `schema_version: 1`，包含 `generated_at`、`report_date`、`window_days`、`is_demo`、`coverage`、`items`、`sources`。来源状态区分：

| 状态 | 含义 |
| --- | --- |
| `ok` | 请求和解析成功，收录了本轮有效标题。 |
| `empty` | 请求和解析成功，但无条目、无符合时间窗的条目，或全部重复；原因另记。 |
| `error` | 网络、HTTP、解析或响应限制错误；`error_code` 与 `attempts` 保留类别，不保存原始错误正文。 |

`coverage.state` 为 `complete`、`partial` 或 `unavailable`，分别表示全部选定源可解析、部分失败、全部失败。`complete` 只说明本轮选定源的请求/解析覆盖，不表示所有新闻都已收全。

- `YYYY-MM-DD.json`、`YYYY-MM-DD.md`：按报告日期保留最近一次有效运行的快照；报告日期默认使用 `Asia/Shanghai`。
- `latest.json`、`最新日报.md`：最近一次有可解析源的快照。
- `last-run.json`：每轮状态，包括全部失败的尝试；看板应同时读取它，避免旧数据被显示为最新。

全部源失败时不覆盖既有 `latest.json`、`最新日报.md` 或同日已有快照。`last-run.json` 标记 `unavailable`、`reused_latest` 和原快照时间；首次即失败时不会伪造最新成功数据。每日文件在没有既有快照时可保留失败报告。程序此时返回退出码 2；有可解析源或离线演示返回 0。

文件逐个原子替换，同一数据目录通过 `.collect.lock` 拒绝并发写入。若进程被强制结束，只在确认无采集进程后手动移除残留锁。采集器不会修改系统定时任务，也不自动删除历史日报；看板只选取其约定的近 14 日日期窗口。
