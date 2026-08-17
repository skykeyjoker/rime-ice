# Agent 上游更新指引

本文供 Codex 等 Agent 定期审查本 Fork。首要目标是跟随雾凇上游，同时保护
Skykey 的万象、云拼音、跨平台词库、独立颜文字、学习数据边界和拆字增强。

## 当前基线与来源

- 主上游：`https://github.com/iDvel/rime-ice.git`，分支 `main`；
- 次级词库参考：`https://github.com/gaboolic/rime-frost.git`，分支 `master`；
- 已审查的精确提交和日期标签记录在 `.upstream/agent-reviewed.yaml`。

雾凇是方案、核心词典和 Lua 的唯一主上游。白霜只用于检查本 Fork 已迁入的
五套词库与 `cn_dicts_cell/` 是否有值得吸收的数据更新；不要从白霜复制 schema、
Lua、OpenCC 或候选排序配置。

## 分支约束

```text
iDvel/rime-ice main -> fork main -> PR -> Mac -> PR -> Windows
```

- `main` 必须保持上游纯净，不得在其上提交 Fork 定制；
- `Mac` 是默认分支和公共定制基线；
- `Windows` 只放平台差异，例如小狼毫云拼音 Lua 和 Windows 迁移文档；
- 自动任务只快进 `main` 并创建 PR，不能自动合并 `Mac` 或 `Windows`。

## 不可破坏的能力

| 能力 | 锚点 | 验收要求 |
| --- | --- | --- |
| 雾凇主方案 | `rime_ice.schema.yaml`、`rime_ice.dict.yaml` | 保持雾凇组件和核心词频；保留腾讯、五套迁移词库及 23 套细胞词库的直接导入 |
| 颜文字 | `kaomoji*`、`lua/kaomoji_isolation.lua` | 普通拼音不混入颜文字；`kmj` + 全拼使用独立翻译器且不触发云查询或用户学习 |
| 用户学习 | `translator/user_dict: rime_ice` | 不二进制改名用户库；不恢复候选 `*`；公开仓库不包含 `*.userdb` 或 `sync/` |
| 万象 LTS | `rime_ice.custom.yaml`、`lua/model_candidate_marker.lua` | 保持上下文建议；模型整句显示 `∞`；模型文件不提交 |
| 云拼音 | `lua/cloud_pinyin_async.lua`、`cloud_pinyin_async` patch | 本地/模型前两位优先；分段选择、回退后继续查询；运行文件和 helper 不提交 |
| 共享短语 | `custom_phrase_shared.txt`、`custom_phrase_user` | 公共固定短语跨平台；私人 stabledb 只留本机 |
| 拆字注音 | `kMandarin17*`、`radical_reading_supplement*`、fallback Lua | Unicode 优先、审计补充次之、最后 `n/a`；两个受控 reverse.bin 不被普通部署重建 |
| 按键/UI | `default.custom.yaml`、`rime_ice.custom.yaml` | 10 个候选；KP Enter 上屏原始拼音；字体和主题由前端文件保留 |

## 一、只读预检

```sh
git status --short --branch
git remote -v
git fetch origin --prune
git fetch upstream main
git branch -vv
```

确认：

1. `upstream` 指向 `iDvel/rime-ice`，`origin` 指向 `skykeyjoker/rime-ice`；
2. 工作区没有来源不明的修改；
3. `origin/main` 可快进到 `upstream/main`，没有历史重写；
4. 当前工作分支不是 `main`。

任一条件不满足时停止写入，先报告差异。不要 reset、force-push 或覆盖用户工作。

## 二、审查雾凇变化

以 `.upstream/agent-reviewed.yaml` 的 `ice_main` 为 `ICE_OLD`，当前
`upstream/main` 为 `ICE_NEW`：

```sh
git log --no-merges --date=short --format='%h %ad %s' "$ICE_OLD..$ICE_NEW"
git diff --stat "$ICE_OLD..$ICE_NEW"
git diff --name-status "$ICE_OLD..$ICE_NEW"
```

逐类判断：

- `cn_dicts/`、`en_dicts/`：通常跟随，但检查本 Fork 直接导入项是否仍存在；
- `rime_ice.schema.yaml`、`default.yaml`：人工合并，重点检查组件索引和过滤器顺序；
- `lua/`：吸收上游修复，同时检查本 Fork Lua 对候选类型、输入分段和用户学习 API
  的假设是否仍成立；
- `radical_pinyin*`、`lua/search.lua`：尊重雾凇与拆字上游的同步关系，不直接重写；
- 构建、GitHub Action、配方：评估是否影响本 Fork 的分支模型及运行时排除项。

若 Action 已建立 `main -> Mac` PR，就在该 PR 上解决冲突；不要把 `Mac` 反向
合并进 `main`。

## 三、审查白霜词库变化

从 `.upstream/agent-reviewed.yaml` 读取 `frost_master` 为 `FROST_OLD`，只读获取
当前白霜 `master`：

```sh
git fetch --no-tags https://github.com/gaboolic/rime-frost.git \
  +refs/heads/master:refs/remotes/audit/rime-frost
FROST_NEW=$(git rev-parse refs/remotes/audit/rime-frost)
git log --no-merges --date=short --format='%h %ad %s' "$FROST_OLD..$FROST_NEW"
git diff --stat "$FROST_OLD..$FROST_NEW" -- \
  cn_dicts/zhwiktionary.dict.yaml cn_dicts/web-slang.dict.yaml \
  cn_dicts/zhwikisource.dict.yaml cn_dicts/zhwiki.dict.yaml \
  cn_dicts/moegirl.dict.yaml cn_dicts_cell/
```

只对以上文件做三方审查。可采用新增、纠音、删除和词频修正，但必须保留雾凇
词典头、导入路径和构建可用性。其他白霜变化一律记录为“超出次级参考范围”，
不要迁入。

## 四、实施与验证

从最新 `Mac` 创建审查分支，合并 `origin/main`，再处理白霜词库的明确选定项：

```sh
git switch Mac
git pull --ff-only origin Mac
git switch -c "agent/upstream-review-$(date +%Y%m%d)"
git merge --no-ff origin/main
```

修改后执行：

```sh
make -C others/script/ build
make -C others/script/ lint
git diff --check
```

确认所有 `rime_ice.dict.yaml` 导入项都存在，并检查暂存区没有以下内容：

```text
installation.yaml
sync/
*.userdb/
wanxiang-lts-zh-hans.gram
cloud_pinyin_async_helper[.exe]
cloud_pinyin_async.request/response/heartbeat/log/lock/bridge
```

在具备 Fcitx5 的 Mac 上必须实际部署并验证：

1. `xian` 第一候选为本地“先”，云候选从第 3 位开始；
2. 长拼音同时出现本地 `∞` 整句和 `☁搜`/`☁谷`；
3. 先选择前半句后，剩余拼音仍触发云候选；回退修改后也能重新查询；
4. `fangjungen` 得到“方均根”，证明 `shulihua` 已导入；
5. `uUhuohuohuo` 显示“焱 yàn、㷋 tán、燊 shēn、燚 yì、歘 chuā”；
6. 缺少两套读音时只在 `uU` 候选显示 `n/a`；
7. `uuid`、`cC1+1`、腾讯词库样例均可用；
8. `kaixin` 不出现颜文字；`kmjkaixin` 只显示颜文字，且等待后不出现云候选；
9. Fcitx5 重启后方案菜单不是空白。

Windows 无法在 Mac 上冒充运行验证；将公共提交合并到 `Windows` 后，严格按照
`WINDOWS_MIGRATION.md` 在真实小狼毫环境执行测试并记录“已验证/未验证”。

## 五、更新记录并传播

只有当每项变化已经采用或明确拒绝、理由已写入提交/PR，并完成验证后，才更新
`.upstream/agent-reviewed.yaml`：

- `ice_main` 和最近的日期标签；
- `frost_master` 和最近的稳定标签；
- `reviewed_at`。

合并顺序固定为：

1. 审查分支合并到 `Mac` 并推送；
2. 创建 `Mac -> Windows` PR；
3. 在 Windows 分支保留平台 Lua 差异，完成真实小狼毫验证后合并；
4. 最终切回 `Mac`，确认工作区干净。

## Agent 输出模板

```markdown
# 上游更新审查

- 雾凇：OLD_SHA -> NEW_SHA；日期标签：OLD_TAG -> NEW_TAG
- 白霜参考：OLD_SHA -> NEW_SHA；稳定标签：OLD_TAG -> NEW_TAG

## 已采用
- 提交 / 文件 / 原因

## 未采用或推迟
- 提交 / 文件 / 原因

## 验证
- 静态构建：...
- Mac Fcitx5：...
- Windows 小狼毫：已验证 / 未执行

## 分支与 PR
- main -> Mac：...
- Mac -> Windows：...
```
