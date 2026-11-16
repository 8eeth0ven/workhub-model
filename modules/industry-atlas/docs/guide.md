[简体中文](guide.md) | [English](guide.en.md)

# 资料格式与研究方法

从一个能回答的问题开始，例如“某类产品的制造地点和替代供给有哪些公开证据？”先选实体，再补属性与来源，最后连接关系。不要先画一张看似完整、证据却无法追溯的大图。

## 文件与命令

所有命令从安装后的模块目录执行。`facts.json` 是自己整理并检查的输入，`data/atlas.json` 是本地资料，`site/index.html` 是生成网页。

```sh
python3 bin/import_data.py --input facts.json --output data/atlas.json
python3 bin/build_data.py --input data/atlas.json
python3 bin/import_data.py --input update.json --output data/atlas.json --merge
python3 bin/build_data.py --input data/atlas.json
```

首次导入可不带 `--merge`；已有资料更新必须带 `--merge`，不带会替换整个快照。不传输入且默认资料不存在时，生成明确的空态。显式指定的坏文件应修正后重新导入，不能当作空资料使用。`--demo` 只生成明显标注的虚构演示。网页不写回资料；更改原始 JSON 后重新导入、生成。

## 最小资料

下面的名称、作用、链接都是虚构示例，`demo` 必须保留为 `true`。

```json
{
  "schema_version": 1,
  "module_id": "industry-atlas",
  "demo": true,
  "entities": [{
    "id": "sample-device",
    "name": "虚构设备甲",
    "kind": "product",
    "industries": ["compute", "energy"],
    "aliases": [],
    "claims": [{
      "id": "sample-role-1",
      "field": "role",
      "value": "仅用于说明数据结构的虚构设备",
      "source_ids": ["sample-source"],
      "status": "disclosed",
      "valid_from": null,
      "valid_to": null,
      "observed_at": "2026-11-16",
      "note": "虚构示例，不是行业事实"
    }]
  }],
  "relations": [],
  "sources": [{
    "id": "sample-source",
    "title": "虚构说明材料",
    "url": "https://example.com/industry-example",
    "kind": "primary",
    "published_at": null,
    "accessed_at": "2026-11-16",
    "independence_group": "sample-origin"
  }],
  "changes": []
}
```

实体 `id` 和声明 `id` 稳定且唯一。产业与类型使用可扩展的小写 slug，常用产业为 `compute`、`automotive`、`energy`；一种实体可同时属于多个产业。别名用于检索，不创建重复实体。

## 属性、时间与状态

`field` 可扩展；未知字段原样显示。常用字段：

| 字段 | 含义与边界 |
| --- | --- |
| `role` / `principle` / `applications` | 作用、工作原理、使用场景，说明对象和范围 |
| `headquarters_origin` | 总部地点，不替代其他地点 |
| `registered_origin` | 法律注册地 |
| `design_origin` | 设计地点，说明对应型号或版本 |
| `manufacturing_origin` | 制造地，区分公司、工厂、产品与时期 |
| `raw_material_origin` | 原料产地，注明材料、环节和适用范围 |
| `specifications` / `capacity` / `lead_time` / `price` | 规格、产能、交期、价格，保留单位、口径和日期 |
| `substitutes` | 替代品或替代路径，明确限制与证据 |

`value` 支持 JSON 标量、小数组或对象。未知用 `null`，不要将猜测填进空白。空缺不自动表示“不适用”；确认不适用时可写有证据的说明。对象最多 6 层、单个值不超过 4 KiB。

所有日期仅用 `YYYY-MM-DD`。`observed_at` 是录入者观察资料的日期；`valid_from`、`valid_to` 是声明适用的起止日期，终点包含当天，未知用 `null`。来源的 `published_at` 和 `accessed_at` 分别为发布和读取日期。页面“资料最近观察”是已录入日期最大值，不表示所有资料在同一天更新。

| `status` | 页面含义 |
| --- | --- |
| `disclosed` | 来源披露；表示材料这样说，不自动证明属实 |
| `verified` | 已标多源核对；要求至少两个不同 `independence_group`，这只是结构门槛 |
| `inferred` | 推断；写明推导步骤、前提与可能反例 |
| `hypothesis` | 假设；写明验证办法，不当事实呈现 |

非空值除假设外必须有关联来源。多家转载同一公告仍属于同源，不能靠改组名制造独立性。校验时会合并组名空白并忽略大小写，避免用这些差异凑组数。分组本身由录入者提供，软件无法证明来源真实独立。`primary` 表示原始材料，`secondary` 表示二手转述；原始材料同样可能有遗漏或错误。

## 关系与历史

每条关系有稳定 `id`、`source` 与 `target` 实体 ID、扩展 `kind`，并内嵌一条 `field: "relationship"` 的完整 `claim`。方向是 `source → target`，含义由 `kind` 和声明值决定；不能将“使用”自动解释为独家供应或因果。关系证据需说明产品、时期、环节和数量口径。

更正用新的声明 ID，并在 `changes` 追加：

```json
{
  "id": "change-1",
  "entity_id": "sample-device",
  "field": "manufacturing_origin",
  "previous_claim_id": "origin-old",
  "new_claim_id": "origin-new",
  "observed_at": "2026-11-16",
  "note": "新材料改变了原声明的适用范围"
}
```

两个声明都必须存在，属于同一实体和字段。关系声明的所有者是关系的 `source`，关系历史连接还需保持相同关系类型。合并不静默改写相同 ID 的内容；修正时追加新 ID。没有变更连接的声明并存，可能互相冲突。页面把有替代连接的旧声明放入历史；“未标替代”不是当前真实或仍有效的证明。

图只展开选中实体一跳，最多 24 节点／36 边；绘线保持正交并避开第三个节点，无法清晰布线时省略绘线并提示，证据仍在列表。图可能跨产业，产业筛选针对实体名单。超过首批的关系列表、属性声明与变更记录可以展开查看。

## 六类追问

选中属性后展开“追问与验证”。规则会检查：问题目标与对象范围；五种地点口径；来源组与原始出处；替代供应、反例与其他解释；成本、交期、毛利和回款；发布、观察、有效期与变更。缺失制造地会问如何取得该产品与时期的工厂证据，不会拿总部补齐。模型整理结果必须人工回到原始来源核对。

数据有输入上限：4 MiB、2,000 实体、5,000 关系、1,000 来源、10,000 声明及 10,000 变更。它们是操作边界，不代表行业覆盖目标。没有记录不代表没有关系，资料新不等于结论可靠。
