[简体中文](collector.md) | [English](collector.en.md)

# AI 产品采集与增量简报

采集公开新闻的标题、链接、来源和时间，不抓全文，也不需要模型 Key。使用 Python 3.10 或更新版本，仅依赖标准库。模块不会创建或修改定时任务。

```sh
# 先用独立目录运行离线虚构演示。
python3 bin/collect.py --demo --data-dir demo/data
python3 bin/build_data.py --data-dir demo/data

# 真实采集使用另外的目录。
cp config.example.json config.json
python3 bin/collect.py --config config.json
python3 bin/build_data.py
```

两个命令默认分别读取和写入本模块的 `data/`、`site/`。自定义数据目录时，给采集器和构建器传相同的 `--data-dir`。真实配置、日报、日志和生成的网页属于本机运行资料，不随源码或 ZIP 发布。

## 25 个采集入口

| 分类 | Google News 查询组数 |
| --- | ---: |
| 国内产品与大模型 | 7 |
| 国际 AI 产品 | 7 |
| AI 硬件与机器人 | 2 |
| AI 人物发言 | 7 |

另有 TechCrunch AI RSS 和百度 AI 相关热搜，共 25 个入口。人物查询把人名、AI 主题和发言词分别分组，减少只命中泛化“表态”的无关新闻；关键词无法保证话题完整或相关性绝对准确。

默认只保留发布日期位于 UTC 精确过去 48 小时的 RSS 新闻，每源最多 25 条。缺失时区、无法解析、未来或窗外日期分别拒收，不把未知时间当作今天。百度热搜缺乏可靠发布日期，使用 `published_at: null`、`observed_at` 和 `time_basis: observed` 记录观察时间。

英文词按边界匹配，避免把 `said` 或 `training` 中的字母误当 `AI`。标题按高关注负面、普通负面、正向、其他关键词分级；标签只是等待核验的线索，不能证明事件属实或等同完整舆情分析。

## 网络与状态

默认直连，不读取环境代理。需要代理时在私有 `config.json` 中填写 `proxy`，或显式传 `--proxy`；百度始终直连。默认不在代理故障时悄悄切换直连，只有 `proxy_fallback_direct: true` 才允许回退。

配置支持 `window_days`、`timezone`、`workers`、`timeout_seconds`、`retries`、`proxy`、`proxy_fallback_direct`、`max_items_per_source`，也可用 `enabled_sources` 选择源。Google ID 为 `google-01` 至 `google-23`，其余是 `techcrunch-ai`、`baidu`。

```sh
python3 bin/collect.py --source techcrunch-ai --source baidu --timeout 5 --retries 0
```

默认并发 4 个源，上限 8；每次请求默认 15 秒、最多重试 1 次，可配置 0～2 次。请求读取检查剩余总预算，限制响应体大小，并把截断响应等协议异常隔离到单个源。状态明确区分：

- `ok`：请求与解析成功，并收录有效标题。
- `empty`：成功解析，但无原始条目、无匹配或全部重复；原因另记。
- `error`：网络、HTTP、解析、协议或响应限制错误；只保留错误类别，不保存原始错误正文。

`coverage.state` 的 complete/partial/unavailable 只说明**本轮选定源**的请求与解析情况，不保证收全了所有新闻。全部源失败时返回退出码 2；存在可解析源或离线演示时返回 0。

## 同日多轮也能比较

每轮有独立 `run_id`。每份成功日报都内嵌同一 run 的 `delta`，不是把一个全局增量结果套到所有历史日期。

| 文件 | 作用 |
| --- | --- |
| `latest.json`、`最新日报.md` | 最近可用快照 |
| `previous.json` | 再上一份可用快照；失败轮不推进它 |
| `last-run.json` | 最近一次尝试，包括全部源失败 |
| `delta.json`、`增量简报.md` | 对应最近一次尝试的差异摘要 |
| `YYYY-MM-DD.json`、`YYYY-MM-DD.md` | 当天最近可用快照，同日成功轮覆盖更新 |
| `seen-index.json` | 最多 14 天、10,000 项的已见内容索引 |
| `.collection-state.json` | 单次原子提交的成功快照、上一快照和索引，用于恢复派生文件 |

内容 ID 绑定去掉追踪参数后的 URL；归一化标题别名用于减少相同标题换来源后重复刷屏，不把不同 URL 强行证明为同一现实事件。同 URL 标题或关键词标签变化记为 `changed`；来源、分类、顺序和观察时间变化不记作内容变化。

有可用近期基线时，`delta` 包含 `new_ids`、`changed_ids`、`unchanged_ids` 与对应计数。当前窗口没有基线时，条目标记 `baseline`，不会假装与上一轮比较后得出了“新增”。`baseline_reason` 区分 missing、expired、future、available。最近成功快照超过 14 天或来自未来时不能作为有效比较基线。

已见索引保留最多 14 天、10,000 个 URL 身份、每项 8 个哈希别名。来源暂时缺失或本轮只采部分源后，恢复出现的已见标题不会轻易再标为新增；没有“消失事件”推断。索引失效时明确说明退回上一有效快照重建。`changed` 表示标题或标签的指纹变化，仍需阅读原文才能判断是否出现实质进展。

全部失败时，`comparison_skipped: true`，不推进成功快照、previous 或已见历史；旧内容不可当成本轮新消息。写入成功 checkpoint 后，扁平 JSON 和 Markdown 都是可恢复视图；中途中断后，下轮会从 checkpoint 恢复，避免已见索引超前导致静默漏报。单个输出文件有 24 MiB 上限。

## 目录隔离

模式标记、快照和增量都记录 `module_id: ai-opinion` 与 `is_demo`。演示与真实数据双向拒绝混用，也拒绝误用车圈模块数据。只有旧 Markdown、无法确认模块身份或损坏状态的目录需要人工复核或改用新目录，不猜测迁移。`.collect.lock` 拒绝同目录并发运行；异常退出后，只在确认没有采集进程时移除残留锁。

数据不会自动发送到 LLM。需要文字简报时，由用户选定的 Agent 按模块提示词读取必要资料；定时任务应由用户另行显式设置。定时频率不构成源可用性或结果质量保证。
