# Skykey Rime Ice Fork

这个仓库是 [`iDvel/rime-ice`](https://github.com/iDvel/rime-ice) 的个人 Fork。
它以雾凇拼音为唯一主方案，在保留上游词典、Lua 和候选排序的基础上，加入
Skykey 跨平台配置。

## 分支结构

| 分支 | 用途 | 更新方式 |
| --- | --- | --- |
| `main` | 雾凇上游的纯净镜像 | GitHub Action 每日调用 Fork 同步接口快进 |
| `Mac` | Fcitx5-macOS 正式配置，也是仓库默认分支 | 人工审查并合并 `main -> Mac` |
| `Windows` | 小狼毫配置及迁移指引 | 从 `Mac` 派生，人工审查并合并 `Mac -> Windows` |

`main` 不承载本 Fork 的自定义内容。这样可以始终准确比较雾凇上游变化，也不会
让无人值守任务覆盖平台配置。`.github/workflows/upstream-sync.yml` 在检测到差异时
创建 PR；配置、Lua、词库冲突必须按照
[`AGENT_UPSTREAM_UPDATE.md`](AGENT_UPSTREAM_UPDATE.md) 审查后再合并。

## 增强内容

- 万象 LTS 模型及 `∞` 模型整句标记；
- [Rime Cloud Pinyin Async](https://github.com/skykeyjoker/rime-cloud-pinyin-async)
  提供非阻塞的搜狗、Google 双源云候选，本地和万象候选保持优先；
- 腾讯词向量、六套迁移词库和 23 套细胞词库直接由
  `rime_ice.dict.yaml` 导入，共用雾凇翻译器、用户词典和万象模型；
- 公开短语 `custom_phrase_shared.txt` 跨平台同步；私有短语使用不入库的
  `custom_phrase_user` stabledb；
- `uU` 拆字使用 Unicode 17 `kMandarin`，缺字时查询经过来源审计的
  Unicode/CNS 补充库，最后才显示 `n/a`；
- 数字小键盘 Enter 与主键盘 Enter 一致，组合态下直接上屏原始拼音；
- 候选页大小为 10；字体、主题和候选窗样式继续由前端配置维护。

## macOS Fcitx5 部署

目标用户目录为：

```text
~/.local/share/fcitx5/rime
```

首次部署前应先退出 Fcitx5，并保留已有的 `installation.yaml`、`sync/`、
`rime_ice.userdb/`、前端主题及私有短语。将 `Mac` 分支的配置复制到用户目录后，
还需要安装以下运行时文件：

1. 从[万象模型 LTS Release](https://github.com/amzxyz/RIME-LMDG/releases/tag/LTS)
   下载 `wanxiang-lts-zh-hans.gram` 到 Rime 用户目录；
2. 按云拼音仓库的
   [Fcitx5-macOS 指引](https://github.com/skykeyjoker/rime-cloud-pinyin-async/tree/main/platforms/macos/fcitx5)
   构建和安装 `cloud_pinyin_async_helper`、刷新 addon；
3. 重新部署并正常重启 Fcitx5。

本仓库不会提交 `.gram`、helper、用户学习库、同步目录或云拼音运行状态。它们是
本机运行时或私人数据，不应进入公共 Git 历史。

Windows 小狼毫的完整 Agent 迁移步骤位于
[`Windows` 分支的 `WINDOWS_MIGRATION.md`](https://github.com/skykeyjoker/rime-ice/blob/Windows/WINDOWS_MIGRATION.md)。

## 数据与第三方资源

- 雾凇拼音本体遵循仓库 [`LICENSE`](LICENSE)；更细的上游词典来源见
  [`others/docs/Credits.md`](others/docs/Credits.md)。
- 六套迁移词库和 `cn_dicts_cell/` 来自
  [`gaboolic/rime-frost`](https://github.com/gaboolic/rime-frost)，保留为独立文件，
  方便追踪来源与更新；其中维基、萌娘百科等数据还可能受各自站点条款约束。
- 腾讯词向量来自 Tencent AI Lab，雾凇 Credits 标注为 CC BY 3.0。
- `kMandarin17` 使用 Unicode 17.0.0 Unihan 数据，遵循
  [Unicode License v3](https://www.unicode.org/license.txt)。
- 拆字补充库同时使用 CNS11643 开放资料，遵循
  [政府资料开放授权条款第 1 版](https://data.gov.tw/license)。精确版本、哈希和生成方式
  见 [`RADICAL_PINYIN.md`](RADICAL_PINYIN.md) 与
  [`RADICAL_READING_SUPPLEMENT.md`](RADICAL_READING_SUPPLEMENT.md)。
- 万象模型与云拼音适配器不重新分发；请分别从其官方仓库下载，并遵守各自许可
  与服务条款。

## 隐私边界

万象模型在本地运行。启用云拼音后，尚未上屏的全拼编码会通过 HTTPS 发送给
搜狗和 Google Input Tools；第三方会自然获得请求的 IP、时间和 User-Agent。
本地词库、用户词典、已上屏正文和剪贴板不会由本项目主动上传。无法接受输入编码
发送给第三方时，应从 `rime_ice.custom.yaml` 移除三个 `cloud_pinyin_async` 组件。

## 基础验证

仓库修改后至少执行：

```sh
make -C others/script/ build
make -C others/script/ lint
git diff --check
```

平台部署后还要检查 `xian` 的本地单字优先、长句 `∞`、第 3 位起的云候选、
分段选词后剩余拼音继续触发云查询、`uUhuohuohuo`、`uuid`、`cC1+1`、
`kmjgx`、腾讯词库和细胞词库样例。
