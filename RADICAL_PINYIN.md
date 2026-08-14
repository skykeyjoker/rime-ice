# 部件拆字与 Unicode 17 注音

本 Fork 使用 `rime-radical-pinyin` 3.1.1 的拆字方案和词典。Unicode 17.0.0
Unihan `kMandarin` 是第一注音来源；缺失时才查询独立、可审计的官方补充库。

## 为什么不再使用 zdict.reverse.bin

旧 `zdict.reverse.bin` 是上游在 2024 年前已经提交的预编译产物，仓库中没有与它一一对应、可重新生成的源词典。现在改为：

1. 固定下载 Unicode 17.0.0 的官方 `Unihan.zip`；
2. 校验固定 SHA-256；
3. 扫描压缩包中的全部 `Unihan*.txt` 并提取 `kMandarin`，不依赖属性当前所在文件名；
4. 对双读音记录采用 Unicode 定义的第一个值，即 zh-Hans（中国大陆简体）优先读音；
5. 生成并提交 `kMandarin17.dict.yaml`；
6. 生成并提交 `build/kMandarin17.reverse.bin`，正常部署直接加载该预编译文件。

`kMandarin17` 和 `radical_reading_supplement` 都不在 `rime_ice.schema.yaml` 的
构建依赖中，因此普通的“重新部署”不会检查或重新编译它们。真正的可复现来源
仍是生成脚本、固定数据哈希和生成后的文本词典；只有维护者升级官方数据或
预编译文件丢失时，才需要执行手动生成流程。

## 补充注音和显示回退

Unicode 没有为所有拆字候选提供 `kMandarin`。`lua/radical_comment_fallback.lua`
位于过滤链末端，只在当前输入严格匹配 `uU[a-z]+` 且候选注音为空时查询
`radical_reading_supplement`；补充库也没有记录时才显示 `n/a`：

- 已有注音（例如 `wēi`、`yàn`）原样保留；
- 普通拼音、英文、万象整句等非 `uU` 候选不受影响；
- 例如 `𢨋` 从补充库显示 `bèi bó`（Rime 反查库按内部音节顺序排列）；
- Lua 使用影子候选承载显示注释，不写入两套来源词典、用户词典或同步数据；
- 普通重新部署只更新方案配置，不需要也不应该重建两个受控 `.reverse.bin`。

`n/a` 表示“两套当前反查读音库都没有可接受记录”，不等于该字没有读音。
补充库的来源、保守规则、覆盖率、审计文件和维护命令见
[`RADICAL_READING_SUPPLEMENT.md`](RADICAL_READING_SUPPLEMENT.md)。

## 重新生成和校验

联网生成：

```sh
python3 scripts/generate_kmandarin17.py
```

脚本只使用 Python 标准库，要求 Python 3.9 或更高版本。

使用已经下载的官方压缩包生成：

```sh
python3 scripts/generate_kmandarin17.py \
  --source-zip /path/to/Unihan.zip
```

确认已提交词典可以逐字节复现：

```sh
python3 scripts/generate_kmandarin17.py --check \
  --source-zip /path/to/Unihan.zip
```

数据约束：

- Unicode 版本：`17.0.0`；
- 官方来源：`https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip`；
- `Unihan.zip` SHA-256：`f7a48b2b545acfaa77b2d607ae28747404ce02baefee16396c5d2d7a8ef34b5e`；
- `kMandarin` 记录数：`44348`；
- 生成词典 SHA-256：`a770bc32b15d13b05c3459642f943689fd1acd4d1c41d4c37867d409e4c8d13a`；
- 使用 Fcitx5-macOS 自带的 librime 1.17.0 编译所得 `build/kMandarin17.reverse.bin` SHA-256：`119c916280a32935967c0310cc0eb4b9d3d4d3f623026d1816f3bd21ff1f2330`。

文本词典已通过重新生成校验；同一份词典使用 librime 1.17.0 清空构建产物后编译两次，得到的 `reverse.bin` 逐字节一致。不同 librime 版本生成的二进制哈希可以不同，不影响以文本词典为基准的可复现性。

生成文本词典后，使用包含 `--compile` 的 `rime_deployer` 单独编译，并把生成的 `build/kMandarin17.reverse.bin` 一并提交：

```sh
rime_deployer --compile kMandarin17.schema.yaml "$PWD" "$PWD" "$PWD/build"
```

补充库需要用它自己的维护方案单独生成，详见 `RADICAL_READING_SUPPLEMENT.md`。

## 验收

- `uUhuohuohuo` 应出现“焱”等候选，注音包含 `yàn`；
- `uUhuohuohuohuo` 应出现“燚”等候选，注音包含 `yì`；
- `uUhuo` 中的 `𪹪` 应由补充库显示 `è`，`𤌪` 应显示 `yān`；
- `uUhuohuo` 下一页的 `𢨋` 应显示多音 `bèi bó`；
- `𤊢`、`𤈝` 没有可接受读音，仍应显示 `n/a`；
- 普通拼音候选不得出现由该过滤器添加的 `n/a`；
- 生成配置中的 `radical_reverse_lookup/dictionary` 应为 `kMandarin17`；
- 连续执行普通重新部署，两个受控反查文件的内容和修改时间均不应变化；
- 只有维护时显式编译对应的维护 schema，才应重新生成相应二进制。

资料来源：[Unicode 17.0.0](https://www.unicode.org/versions/Unicode17.0.0/)、[UAX #38 kMandarin](https://www.unicode.org/reports/tr38/#kMandarin)、[rime-radical-pinyin](https://github.com/mirtlecn/rime-radical-pinyin/releases/tag/3.1.1)。
