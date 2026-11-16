[简体中文](modules.md) | [English](modules.en.md)

# 下载与接入功能模块

`workhub-model` 存放可独立下载的 Workhub 功能模块。它不是模型权重库，也不替换 Workhub 本身。先下载仓库，再从本地目录安装所需模块；模块安装只复制明确列出的源码，不联网采集、不运行脚本、不创建定时任务。

需要 Python 3.10 或更新版本，分发工具使用标准库。

```sh
git clone https://github.com/8eeth0ven/workhub-model.git
cd workhub-model
python3 manage.py list
python3 manage.py install auto-opinion --output ../my-auto-opinion --dry-run
python3 manage.py install auto-opinion --output ../my-auto-opinion
```

输出目录必须不存在，已有目录即使为空也不会覆盖。`--dry-run` 校验模块文件并显示清单，不创建输出目录。安装后的 `module-install.json` 记录版本和每个源码文件的 SHA-256；数据、日报、日志和后续个人配置都留在安装目录，勿提交到发布仓库。

进入安装目录后，可先生成明确标注的离线虚构演示，再按模块说明配置正式采集：

```sh
cd ../my-auto-opinion
python3 bin/build_data.py --demo
```

查看生成的 `site/index.html`。安装工具不会自动启动服务器或采集新闻。真实采集命令、网络配置与信息边界见模块 README。

## 接入 Workhub

先生成看板，再显式指定自己的 Workhub 源码目录。下面的 `/path/to/workhub` 是占位路径，需替换为实际目录：

```sh
python3 manage.py connect auto-opinion \
  --installed ../my-auto-opinion --workhub /path/to/workhub --dry-run
python3 manage.py connect auto-opinion \
  --installed ../my-auto-opinion --workhub /path/to/workhub
```

这两条命令从 `workhub-model` 仓库目录执行。`connect` 调用所选本机 Workhub 的项目安装器，登记项目与静态站点；它不安装全局规则、不启动采集或服务、不创建自动化。尚未生成 `site/index.html` 时会报错，不把登记成功当作网站运行成功。

## 单模块 ZIP

```sh
python3 manage.py package auto-opinion --output ../auto-opinion-0.1.0.zip --dry-run
python3 manage.py package auto-opinion --output ../auto-opinion-0.1.0.zip
```

ZIP 顶层为 `auto-opinion/`，只包含 `module.json` 明确列出的源码、文档和脱敏提示词。现有 ZIP 不会被覆盖；输出会给出包的 SHA-256。文件顺序、时间戳和权限固定，便于校验同一源码产生的包。安装和打包都不会自动下载或执行远程代码。

## 增加模块

在 `modules/<module-id>/module.json` 定义版本、入口和 `files` 明确清单，再把相同版本加入根 `catalog.json`。模块 ID 使用小写字母、数字和短横线。源码清单不允许目录通配符、绝对路径、`..`、反斜线、符号链接或特殊文件；测试、数据、日志、凭据配置和生成的 `index.html` 也会被拒绝。

分发前逐项查看实际文件、配置与配图。工具会拦截已知个人路径、常见令牌、私钥、带凭据的 URL 和本机自动化标识，但启发式检查不保证识别所有敏感信息。新版本安装到新目录，核对后再自行迁移个人配置与数据；当前工具不自动覆盖升级。

## 独立后端模块

需要后端持久化的模块要先按其README显式启动本机服务，再给`connect`传`--site-url http://127.0.0.1:8831/`。此参数只接受不含凭据、查询或片段的回环HTTP(S)地址；连接只登记，不启动服务。server模块省略该参数会报错，避免把静态预览误当作可写后端。

## 模块界面

复用共享设计变量与Codex明亮，优先内容、常用导航和搜索。次要选项按需展开，避免整排筛选框和重复提示；使用字阶、细线与少量轻表面组织内容，不为每条资料或单词套独立边框。设置展开向下推动布局，保留正文阅读空间。正常状态合并，失败、旧数据、来源和证据仍须可查。
