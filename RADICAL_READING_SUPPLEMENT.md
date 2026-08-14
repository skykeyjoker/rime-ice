# 拆字补充注音的来源与维护

`kMandarin17` 始终是本 Fork 的第一注音来源。补充库只处理
`radical_pinyin.dict.yaml` 中存在、但 Unicode 17 `kMandarin` 没有读音的单字，
不会覆盖或合并进 `kMandarin17.dict.yaml`。

运行时顺序如下：

1. `reverse_lookup_filter` 从 `build/kMandarin17.reverse.bin` 取得 Unicode 注音；
2. 只有注音为空时，`lua/radical_comment_fallback.lua` 才查询
   `build/radical_reading_supplement.reverse.bin`；
3. 两套反查库都没有记录时，Lua 显示 `n/a`。

因此，已有的 `kMandarin` 注音不会被台湾读音或异体传播结果改写，补充库也不会
进入用户词典、同步数据或雾凇主拼音词典。

## 数据来源与接受规则

生成器 `scripts/generate_radical_reading_supplement.py` 固定并校验三份官方数据：

| 数据 | 版本 | SHA-256 |
| --- | --- | --- |
| Unicode `Unihan.zip` | 17.0.0 | `f7a48b2b545acfaa77b2d607ae28747404ce02baefee16396c5d2d7a8ef34b5e` |
| CNS11643 `Properties.zip` | 20260805 | `3d56ef14cc8099893245dac58fe4718d2fa64812b9159352a98a4588ad3efa5c` |
| CNS11643 `MapingTables.zip` | 20260805 | `4502fcf7b433d679dee51127298929543ec7f4aa99be93cd219df1552bc3d2bf` |

按以下顺序补全，前一级已有结果时不使用后一级：

1. Unihan 的直接普通话字段：`kHanyuPinlu`、`kTGHZ2013`、`kXHC1983`、
   `kHanyuPinyin`、`kSMSZD2003Readings`；
2. 仅通过 `kCompatibilityVariant`、`kZVariant` 传播，并要求同一连通组中
   所有已有读音集合完全一致；
3. CNS11643 官方注音经官方 `CNS_pinyin_2.txt` 转为汉语拼音；
4. 加入 CNS 后再执行一次相同的严格等价传播。

不会使用反切推导现代读音，也不会通过语义异体或简繁关系传播读音。

CNS 数据中 `mǒu` 大量出现在其他权威来源已有不同读音的字符上。官方说明没有
明确把它定义为占位符，但数据交叉验证强烈显示它不能被批量当作真实读音。因此
生成器会删除精确的 `mǒu`；删除后无其他读音的字符继续显示 `n/a`。确需恢复的
真实 `mǒu` 读音必须经过第二来源人工核验，不能放宽全局规则。

## 当前结果

以 `radical_pinyin` 3.1.1、Unicode 17.0.0 和 CNS11643 20260805 生成：

| 项目 | 数量 |
| --- | ---: |
| 拆字词典中的 Unicode 汉字 | 92,487 |
| `kMandarin17` 已覆盖 | 43,208（46.72%） |
| 补充库新增汉字 | 25,543 |
| 补充库词典行 | 31,192 |
| 合计覆盖 | 68,751（74.34%） |
| 仍显示 `n/a` | 23,736 |

补充来源分布为：Unihan 直接字段 12 字、Unicode 严格异体传播 12 字、CNS
直接数据 25,517 字、加入 CNS 后严格异体传播 2 字。补充库中有 4,314 个多音字。

受控产物：

- `radical_reading_supplement.dict.yaml` SHA-256：
  `67892c0a19525789ef5bcad35bf63bd823d581cdc50201a931eceebe30058c92`；
- librime 1.17.0 生成的 `build/radical_reading_supplement.reverse.bin`
  SHA-256：`210e78a05f5b226219d0cbbe76c061c9f5b61a500c8dfb9cbba61c652889c244`。

审计文件：

- `radical_reading_supplement.provenance.tsv`：每个补充字的读音、层级、
  Unicode 属性或 CNS 字码及 CNS 来源说明；
- `radical_reading_supplement.conflicts.tsv`：CNS 与 `kMandarin17` 不一致的
  项目，运行时一律保留 `kMandarin17`；
- `radical_reading_supplement.unresolved.tsv`：应用全部保守规则后仍无读音的字符。

## 生成、编译与校验

联网生成：

```sh
python3 scripts/generate_radical_reading_supplement.py
```

使用已下载的官方压缩包：

```sh
python3 scripts/generate_radical_reading_supplement.py \
  --unihan-zip /path/to/Unihan.zip \
  --cns-properties-zip /path/to/Properties.zip \
  --cns-mappings-zip /path/to/MapingTables.zip
```

逐字节校验全部文本产物：

```sh
python3 scripts/generate_radical_reading_supplement.py --check \
  --unihan-zip /path/to/Unihan.zip \
  --cns-properties-zip /path/to/Properties.zip \
  --cns-mappings-zip /path/to/MapingTables.zip
```

只有数据版本或生成规则经过人工审查后，才显式编译维护方案并提交新的反查文件：

```sh
rime_deployer --compile radical_reading_supplement.schema.yaml \
  "$PWD" "$PWD" "$PWD/build"
```

只提交 `build/radical_reading_supplement.reverse.bin`；编译同时产生的 `.table.bin`、
`.prism.bin` 和构建版 schema 仍是普通缓存。补充方案不加入雾凇 schema 依赖，
所以正常“重新部署”直接读取已提交的反查文件，不会检查或重建它。

更新数据时必须同时审查来源版本、哈希、覆盖率、冲突报告、`mǒu` 过滤和样例，
不能让定时任务盲目合并。生成器内置的当前基线与样例包括：

- `𢨋` 的来源顺序为 `bó bèi`；编译后 Rime 按内部音节顺序显示 `bèi bó`；
- `𪹪` → `è`；
- `𤌪` → `yān`；
- `𤊢`、`𤈝` 只有被过滤的 CNS `mǒu`，仍保持未解决。

## 授权与归属

- Unicode 数据由 Unicode, Inc. 提供，依照
  [Unicode License v3](https://www.unicode.org/license.txt) 使用；
- CNS11643 数据来源为台湾数位发展部“全字库中文标准交换码”，依照
  [政府资料开放授权条款第 1 版](https://data.gov.tw/license) 使用；版本与下载入口见
  [CNS11643 开放资料](https://data.gov.tw/dataset/5961) 和
  [官方 release.txt](https://www.cns11643.gov.tw/opendata/release.txt)。

这些授权和来源说明必须与生成词典及审计文件一起保留。
