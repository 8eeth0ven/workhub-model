[简体中文](guide.md) | [English](guide.en.md)

# 使用与边界

先在小项目或明确选择的目录索引，核对一个已知函数，再用图扩大阅读范围。模块提供静态代码关系与学习资料检索，不搜索整台电脑或聊天会话。

```sh
python3 bin/query_graph.py --input data/latest.json query "parse"
python3 bin/query_graph.py --input data/latest.json context UNIQUE_SYMBOL
python3 bin/query_graph.py --input data/latest.json impact UNIQUE_SYMBOL --hops 2
python3 bin/query_graph.py --input data/latest.json trace FROM_SYMBOL TO_SYMBOL
```

选择器用节点 ID 或唯一的限定名；同名歧义时明确报错，不能任意选一个。关系选项 `--edge-kind calls|imports|contains|all` 默认调用，context/impact/trace均支持。

| 关系 | 含义 | 边界 |
| --- | --- | --- |
| contains | 源码结构中的包含 | 不代表调用 |
| imports | 对本次索引内模块的静态导入关系 | 不代表导入时或之后必定执行 |
| calls | 保守匹配到的调用表达式目标 | 不等于动态运行证明 |

trace按有向边做无权BFS，返回最少边数的一条路径；impact反向查潜在调用者，受跳数和已解析边范围限制。没有路径只能说明当前选定图中未找到。图视图的节点截断与索引覆盖是两种限制，应分别检查。

资料库为17条AI原生工程进阶官方入口，附原创建议实验和自检。默认不列基础编程教程。前沿更新从七个官方仓库各读取一页最多六条 GitHub Releases，再筛选近 90 天；这不是窗口内完整历史，也不保证严格最新六条。保留预发布、空源、失败和旧数据状态；不覆盖所有论文、提交和产业消息。GraphRAG、时序知识图谱与MCP是研究资料，不代表本模块已实现对应完整系统。

GitNexus官方参考：[README](https://github.com/abhigyanpatwari/GitNexus)、[MCP工具](https://github.com/abhigyanpatwari/GitNexus/blob/main/docs/mcp-reference.md)、[架构](https://github.com/abhigyanpatwari/GitNexus/blob/main/ARCHITECTURE.md)、[许可证](https://github.com/abhigyanpatwari/GitNexus/blob/main/LICENSE)。本版只参考检索与证据呈现思路，未安装、复制或宣称达到其覆盖范围。
