[简体中文](README.md) | [English](README.en.md)

# 车圈舆情监控

把公开汽车新闻、汽车相关热搜和采集状态放到一个可接入 Workhub 的本地看板。

默认采用 Workhub 已有的 Codex 明亮风格：白色内容、浅灰底色、深色文字，与 Workhub 共用配色和紧凑排版；已有保存的配色偏好继续保留。

## 使用

```sh
# 离线虚构演示，不访问新闻源。
python3 bin/collect.py --demo --data-dir demo/data
python3 bin/build_data.py --data-dir demo/data
```

打开 `site/index.html`。真实采集执行：

```sh
cp config.example.json config.json
python3 bin/collect.py --config config.json
python3 bin/build_data.py
```

演示使用独立的 `demo/data/`，真实采集默认使用 `data/`；两种数据不能放进同一目录。配置里的代理默认为空，按自己的网络情况填写。数据默认写入本模块 `data/`，也可给两个命令传相同的 `--data-dir`；构建器支持 `--output-dir`。不要把真实 `config.json`、日报、日志或生成的网页提交到仓库。

## 看什么

| 分区 | 内容 |
| --- | --- |
| 负面线索 | 标题命中的高、中风险关键词，等待核对原始报道 |
| 理想专项 | 产品、交付、销量和相关舆论 |
| 国内车企 | 国内品牌与行业新闻 |
| 国际车圈 | 国际品牌及电动车新闻 |
| 热搜 | 百度热搜中筛选出的汽车相关条目 |

看板保留最近 14 个日历日，支持日期、类别和关键词筛选。RSS 新闻按精确时间窗过滤；热搜没有可靠发布日期时标记为采集时观察，不能冒充三天内发布的新闻。

`last-run.json` 表示最近一次采集状态；`latest.json` 是最近可用的数据。全部源失败时，后者可以保留旧数据，看板须显示采集失败和原数据时间。没有命中关键词不能证明没有负面事件，覆盖缺失时更不能给出这种结论。

## 简报提示词

将 [每日简报提示词](prompts/daily-brief.md) 交给自己使用的 Agent。它按“负面线索 → 理想专项 → 国内外要闻与热搜 → 日报链接”输出；先完成简报，再构建看板，构建失败单独说明。提示词是从用户给出的流程整理的脱敏版本，不含原设备路径或自动化身份。

模块不会创建定时任务。每日 09:00 是可选的使用安排；要定时运行，应在自己选定的自动化工具中显式配置。

完整选项和源状态见 [采集说明](docs/collector.md)。安装来源与导出边界见仓库的 [模块协议](https://github.com/8eeth0ven/workhub-model/blob/main/docs/modules.md)。独立 ZIP 的使用不依赖仓库文档。

新版 Workhub 采用手动入库：登记网站后，仍需你在「接入项目」选择本模块目录并加入中控。网站默认保留自己的外观；需要跟随门户配色时由你显式选择。
