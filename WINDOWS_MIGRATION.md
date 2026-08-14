# Windows 小狼毫全量迁移指引（供 Codex Agent 使用）

本文用于让 Windows 电脑上的 Codex Agent 把现有 Rime/白霜配置完整迁移到本
Fork 的雾凇拼音，并接入万象 LTS 和异步云拼音。目标平台为 64 位 Windows 10/11、
小狼毫（Weasel）和全拼，目标分支为 `Windows`。

> 给 Windows Codex 的开场指令：完整阅读本文件后再执行。先只读定位真实 Rime
> 用户目录、小狼毫安装目录、旧方案、用户学习库和 UI 配置。任何写入前必须创建
> 可读取的完整 ZIP，并成功导出旧用户词典。遇到路径不明确、导出/备份/下载校验
> 失败时停止；不得猜路径、不得二进制重命名用户库、不得删除失败现场。

## 目标结果

- 只启用 `rime_ice`，不再加载 `rime_frost`；
- 保留已有的用户学习、公开/私有短语和额外自定义词库；
- 保留小狼毫字体、字号、主题、布局和候选数量；
- 使用雾凇原生主词典，同时直接导入腾讯、六套迁移词库和全部 23 套细胞词库；
- 启用最新万象 LTS 简体模型，整句候选显示 `∞`；
- 关闭词语自动补全，输入的音节不会被更长词条自动补出额外后缀；
- 云候选由独立 helper 异步查询，显示 `☁搜`、`☁谷` 或 `☁搜谷`，默认位于两个
  本地/模型候选之后；
- `uU` 拆字依次查询 Unicode 17、审计补充库，最后显示 `n/a`；
- `uuid`、日期、计算器、颜文字和数字小键盘 Enter 等能力可用；
- 迁移前完整目录保存在用户目录之外的 ZIP，失败时可回滚。

## 安全边界

1. Git 仓库必须位于 Rime 用户目录之外，例如“文档”目录。
2. 真实用户目录优先读取 `HKCU:\Software\Rime\Weasel` 的 `RimeUserDir`；只有
   未设置时才使用 `%APPDATA%\Rime`。
3. 写入前正常退出小狼毫，并确认 `WeaselServer` 不再运行。
4. 完整 ZIP 必须位于用户目录和 Git 仓库之外，能够打开且条目数大于 0。
5. `rime_frost.userdb` 不能改名成 `rime_ice.userdb`；必须通过 librime levers
   文本接口导出/导入，本仓库使用 `scripts/rime_userdb_tool.py` 调用已安装的
   `rime.dll`。
6. 不向公开仓库提交 `installation.yaml`、`user.yaml`、`sync/`、`*.userdb/`、
   `custom_phrase_user*`、模型、helper 或云拼音运行文件。
7. 不对用户目录、用户主目录、盘符根目录或通配路径执行递归删除。迁移使用改名
   留存旧目录，确认成功前不清理。

## 前置条件

- 小狼毫已安装并包含 `librime-lua`；
- PowerShell 5.1 或更高版本、Git、Python 3.8+、可用的 .NET Framework 4.x
  C# 编译器；
- 建议至少 4 GB 空闲空间，用于 Git 仓库、完整 ZIP、旧目录留存和万象模型；
- 网络可访问 GitHub 与 GitHub Releases；
- 当前只验证全拼，双拼不属于这份迁移单的验收范围。

## 一、克隆两个仓库

```powershell
$documents = [Environment]::GetFolderPath('MyDocuments')
$repo = Join-Path $documents 'rime-ice-skykey'
$cloudRepo = Join-Path $documents 'rime-cloud-pinyin-async'

git clone --branch Windows --single-branch `
  https://github.com/skykeyjoker/rime-ice.git $repo
git clone https://github.com/skykeyjoker/rime-cloud-pinyin-async.git $cloudRepo
```

仓库已存在时只允许快进更新：

```powershell
git -C $repo fetch origin
git -C $repo switch Windows
git -C $repo pull --ff-only origin Windows
git -C $cloudRepo pull --ff-only
```

确认 `$repo` 不在 Rime 用户目录中，并记录两个仓库的精确提交：

```powershell
git -C $repo rev-parse HEAD
git -C $cloudRepo rev-parse HEAD
```

## 二、只读定位与盘点

定位真实用户目录：

```powershell
$weaselReg = Get-ItemProperty 'HKCU:\Software\Rime\Weasel' `
  -ErrorAction SilentlyContinue
$rimeUser = if ($weaselReg -and $weaselReg.RimeUserDir) {
    [Environment]::ExpandEnvironmentVariables([string]$weaselReg.RimeUserDir)
} else {
    Join-Path $env:APPDATA 'Rime'
}
$rimeUser = [IO.Path]::GetFullPath($rimeUser)

[PSCustomObject]@{
    Repository = $repo
    CloudRepository = $cloudRepo
    RimeUserDirectory = $rimeUser
}
Get-ChildItem -LiteralPath $rimeUser -Force |
  Select-Object Name, Length, LastWriteTime
```

如果目录不存在、为空或内容明显不是当前小狼毫目录，停止并向用户确认。

定位小狼毫程序时，先读取卸载注册表的 `InstallLocation`，再检查常用目录；不要
递归扫描整个系统盘：

```powershell
$uninstallRoots = @(
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$installDirs = foreach ($key in $uninstallRoots) {
    Get-ItemProperty $key -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -match '小狼毫|Weasel' } |
      ForEach-Object { $_.InstallLocation }
}
$installDirs += @(
  (Join-Path $env:ProgramFiles 'Rime'),
  (Join-Path $env:LOCALAPPDATA 'Programs\Rime')
)
$weaselServer = $installDirs | Where-Object { $_ } |
  ForEach-Object {
      Get-ChildItem -LiteralPath $_ -Filter WeaselServer.exe -File -Recurse `
        -ErrorAction SilentlyContinue
  } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$weaselDeployer = if ($weaselServer) {
    Get-ChildItem -LiteralPath $weaselServer.DirectoryName `
      -Filter WeaselDeployer.exe -File | Select-Object -First 1
}
$rimeDll = if ($weaselServer) {
    Get-Item -LiteralPath (Join-Path $weaselServer.DirectoryName 'rime.dll') `
      -ErrorAction SilentlyContinue
}
$python = Get-Command python.exe -ErrorAction SilentlyContinue
$userDbTool = Get-Item -LiteralPath (Join-Path $repo 'scripts\rime_userdb_tool.py') `
  -ErrorAction SilentlyContinue
$weaselServer, $weaselDeployer, $rimeDll, $python, $userDbTool |
  Format-List FullName, Source
```

五项中任一缺失时，不要猜路径或从其他版本复制 DLL。由 Agent 查看小狼毫快捷方式、
安装记录或实际安装包后精确定位；在找到匹配版本前停止迁移。官方 Weasel 0.17.4
安装器可能不包含 `rime_dict_manager.exe`，不要因此下载另一个版本的同名工具。
`rime_userdb_tool.py` 直接加载与当前小狼毫同目录的 `rime.dll`，调用相同的 levers
文本导出/导入 API，并且不会重命名或直接改写 LevelDB 文件。

盘点并记录：

- `default.custom.yaml` 的方案列表、候选数量和按键；
- `weasel.custom.yaml` 的字体、字号、横/竖排、颜色和布局；
- `rime_frost.userdb/`、`rime_ice.userdb/`、`sync/`；
- `custom_phrase*`、所有额外 `*.dict.yaml` 和它们的 `import_tables`；
- 一个用户自定义词和一个 Windows 私有短语，作为迁移后样例；
- 当前万象模型的大小和 SHA-256（若存在）。

```powershell
Get-ChildItem -LiteralPath $rimeUser -Recurse -File -Include '*.yaml' |
  Select-String -Pattern 'schema_list|page_size|font|color_scheme|import_tables|user_dict'
Get-ChildItem -LiteralPath $rimeUser -Force -Directory -Filter '*.userdb'
```

## 三、迁移前准备运行时文件

### 3.1 构建 Windows 云拼音 helper

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& (Join-Path $cloudRepo 'platforms\windows\build.ps1')
$cloudHelper = Join-Path $cloudRepo `
  'platforms\windows\dist\cloud_pinyin_async_helper.exe'
if (-not (Test-Path -LiteralPath $cloudHelper)) {
    throw "Cloud helper build failed: $cloudHelper"
}
```

`Windows` 分支已经包含匹配小狼毫的 `lua\cloud_pinyin_async.lua`；不要用 macOS
Lua 覆盖它。

### 3.2 下载并校验最新万象 LTS

先下载到用户目录之外，网络或校验失败时不得修改现有配置：

```powershell
$stage = Join-Path $env:TEMP ("rime-ice-stage-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
$modelStage = Join-Path $stage 'wanxiang-lts-zh-hans.gram'
$release = Invoke-RestMethod `
  'https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/LTS'
$asset = $release.assets |
  Where-Object name -eq 'wanxiang-lts-zh-hans.gram' |
  Select-Object -First 1
if (-not $asset) { throw 'Wanxiang LTS simplified model asset was not found.' }
Invoke-WebRequest $asset.browser_download_url -OutFile $modelStage

$modelHash = (Get-FileHash -LiteralPath $modelStage -Algorithm SHA256).Hash.ToLowerInvariant()
if ((Get-Item -LiteralPath $modelStage).Length -ne [Int64]$asset.size) {
    throw 'Wanxiang model size does not match the GitHub release asset.'
}
if ($asset.digest -and $asset.digest -match '^sha256:(.+)$' -and
    $modelHash -ne $Matches[1].ToLowerInvariant()) {
    throw 'Wanxiang model SHA-256 does not match the GitHub release digest.'
}
[PSCustomObject]@{
    Asset = $asset.name
    Bytes = $asset.size
    SHA256 = $modelHash
    ReleaseUpdatedAt = $asset.updated_at
}
```

## 四、停止小狼毫、备份并导出学习数据

先正常退出：

```powershell
& $weaselServer.FullName /q
Start-Sleep -Seconds 2
if (Get-Process WeaselServer -ErrorAction SilentlyContinue) {
    throw 'WeaselServer is still running; stop here.'
}
Get-Process cloud_pinyin_async_helper -ErrorAction SilentlyContinue |
  Stop-Process -ErrorAction Stop
```

创建完整 ZIP：

```powershell
$backupRoot = Join-Path $documents 'RimeBackups'
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $backupRoot "weasel-before-rime-ice-$stamp.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory(
    $rimeUser,
    $backup,
    [IO.Compression.CompressionLevel]::Optimal,
    $false
)
$zip = [IO.Compression.ZipFile]::OpenRead($backup)
try {
    if ($zip.Entries.Count -eq 0) { throw 'Backup ZIP is empty.' }
    [PSCustomObject]@{
        Path = $backup
        Entries = $zip.Entries.Count
        Bytes = (Get-Item -LiteralPath $backup).Length
    }
} finally {
    $zip.Dispose()
}
```

导出旧学习库。仓库工具显式接收安装目录和用户目录，并输出记录数、文件大小与
SHA-256：

```powershell
$frostExport = Join-Path $backupRoot "rime_frost-$stamp.userdb.txt"
$iceBeforeExport = Join-Path $backupRoot "rime_ice-before-$stamp.userdb.txt"
$userDbCommon = @(
  $userDbTool.FullName,
  '--install-dir', $weaselServer.DirectoryName,
  '--user-dir', $rimeUser
)
if (Test-Path -LiteralPath (Join-Path $rimeUser 'rime_frost.userdb')) {
    & $python.Source @userDbCommon export `
      --dict rime_frost --text-file $frostExport
    if ($LASTEXITCODE -ne 0) { throw 'Failed to export rime_frost userdb.' }
}
if (Test-Path -LiteralPath (Join-Path $rimeUser 'rime_ice.userdb')) {
    & $python.Source @userDbCommon export `
      --dict rime_ice --text-file $iceBeforeExport
    if ($LASTEXITCODE -ne 0) { throw 'Failed to export rime_ice userdb.' }
}
```

若存在 Frost 用户库但导出文本不存在或没有有效词条，停止。ZIP 是回滚资产，文本
导出则用于跨词典名迁移；两者不能互相替代。

## 五、建立纯雾凇用户目录

把旧目录改名留存，再创建新目录；不要在原目录中混合覆盖：

```powershell
$legacy = "$rimeUser.frost-$stamp"
Move-Item -LiteralPath $rimeUser -Destination $legacy
New-Item -ItemType Directory -Path $rimeUser | Out-Null
```

复制 Rime 必需的仓库文件：

```powershell
foreach ($directory in @('cn_dicts', 'cn_dicts_cell', 'en_dicts', 'lua', 'opencc')) {
    Copy-Item -LiteralPath (Join-Path $repo $directory) `
      -Destination $rimeUser -Recurse -Force
}
Get-ChildItem -LiteralPath $repo -File |
  Where-Object { $_.Extension -in @('.yaml', '.txt', '.lua') } |
  Copy-Item -Destination $rimeUser -Force

$build = Join-Path $rimeUser 'build'
New-Item -ItemType Directory -Force -Path $build | Out-Null
Copy-Item -LiteralPath (Join-Path $repo 'build\kMandarin17.reverse.bin') `
  -Destination $build -Force
Copy-Item -LiteralPath `
  (Join-Path $repo 'build\radical_reading_supplement.reverse.bin') `
  -Destination $build -Force
```

恢复明确的本机数据和前端配置：

```powershell
foreach ($file in @('installation.yaml', 'user.yaml', 'weasel.custom.yaml')) {
    $source = Join-Path $legacy $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $rimeUser -Force
    }
}
Get-ChildItem -LiteralPath $legacy -File -Filter 'custom_phrase_user*' `
  -ErrorAction SilentlyContinue |
  Copy-Item -Destination $rimeUser -Force
if (Test-Path -LiteralPath (Join-Path $legacy 'sync')) {
    Copy-Item -LiteralPath (Join-Path $legacy 'sync') `
      -Destination $rimeUser -Recurse -Force
}
if (Test-Path -LiteralPath (Join-Path $legacy 'rime_ice.userdb')) {
    Copy-Item -LiteralPath (Join-Path $legacy 'rime_ice.userdb') `
      -Destination $rimeUser -Recurse -Force
}
```

不要整份恢复旧 `default.custom.yaml`，否则会把方案列表切回白霜。让 Agent 对照旧文件
逐键合并：保留候选数量和其他通用按键，但最终必须满足：

```yaml
patch:
  schema_list:
    - schema: rime_ice
  "menu/page_size": 10  # 若迁移前不是 10，使用迁移前的用户值
```

`weasel.custom.yaml` 可整体保留，因为字体、主题和布局属于前端；若其中含按方案名
覆盖项，把 `rime_frost` 键人工改成 `rime_ice`，不要恢复旧 `weasel.yaml`。

安装已经校验的运行时文件：

```powershell
Copy-Item -LiteralPath $modelStage `
  -Destination (Join-Path $rimeUser 'wanxiang-lts-zh-hans.gram') -Force
Copy-Item -LiteralPath $cloudHelper `
  -Destination (Join-Path $rimeUser 'cloud_pinyin_async_helper.exe') -Force
```

## 六、部署并合并用户学习库

首次部署：

```powershell
& $weaselDeployer.FullName /deploy
if ($LASTEXITCODE -ne 0) { throw 'Initial Weasel deployment failed.' }
```

将旧 Frost 学习数据导入 Ice，已有 Ice 用户库会自动合并：

```powershell
if (Test-Path -LiteralPath $frostExport) {
    & $python.Source @userDbCommon import `
      --dict rime_ice --text-file $frostExport
    if ($LASTEXITCODE -ne 0) { throw 'Failed to import Frost learning data into Ice.' }
}
$iceAfterExport = Join-Path $backupRoot "rime_ice-after-$stamp.userdb.txt"
& $python.Source @userDbCommon export `
  --dict rime_ice --text-file $iceAfterExport
if ($LASTEXITCODE -ne 0) { throw 'Failed to verify the merged Ice userdb.' }
```

按“词 + 编码”比较，确认没有 Frost 独有键丢失：

```powershell
function Get-RimeUserKeys([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    @(Get-Content -LiteralPath $Path -Encoding UTF8 |
      Where-Object { $_ -and -not $_.StartsWith('#') } |
      ForEach-Object {
          $fields = $_ -split "`t"
          if ($fields.Count -ge 2) { "$($fields[0])`t$($fields[1])" }
      } | Sort-Object -Unique)
}
$frostKeys = @(Get-RimeUserKeys $frostExport)
$iceKeys = @(Get-RimeUserKeys $iceAfterExport)
$missingKeys = @()
if ($frostKeys.Count -gt 0) {
    $missingKeys = @(Compare-Object -ReferenceObject $frostKeys `
      -DifferenceObject $iceKeys | Where-Object SideIndicator -eq '<=')
}
[PSCustomObject]@{
    FrostKeys = $frostKeys.Count
    IceKeys = $iceKeys.Count
    MissingFrostKeys = $missingKeys.Count
}
if ($missingKeys.Count -ne 0) {
    $missingKeys | Select-Object -First 20
    throw 'Some Frost learning keys were not imported into Ice.'
}
```

再次部署并启动：

```powershell
& $weaselDeployer.FullName /deploy
if ($LASTEXITCODE -ne 0) { throw 'Final Weasel deployment failed.' }
Start-Process -FilePath $weaselServer.FullName
```

## 七、结构与功能验收

先检查生成配置：

```powershell
$compiled = Join-Path $rimeUser 'build\rime_ice.schema.yaml'
if (-not (Test-Path -LiteralPath $compiled)) {
    throw 'Compiled rime_ice.schema.yaml is missing.'
}
Select-String -LiteralPath $compiled -Pattern @(
  'language: wanxiang-lts-zh-hans',
  'cloud_pinyin_async',
  'dictionary: kMandarin17',
  'radical_reading_supplement',
  'model_candidate_marker'
)
Get-ChildItem -LiteralPath $rimeUser -Force -Filter 'rime_frost*'
```

最后一条应没有输出；新用户目录中不应存在白霜源码、构建文件或用户库。

从小狼毫方案菜单选择“雾凇拼音”，逐项测试：

1. 输入 `xian`，本地单字“先”应排第一；云候选默认从第 3 位开始。
2. 输入 `chabuduojiukeyishidianhouxiabanle`，应看到带 `∞` 的本地模型整句和
   带 `☁` 的云句；选择“差不多”后，剩余拼音仍会继续产生云候选。
3. 在长输入中确认前半段候选后再回退修改，云候选能按新输入重新出现，旧结果不串入。
4. 输入 `mingtianshangwu`，首选应为“明天上午”，不能自动补成“明天上午来”。
5. 输入 `fangjungen`，第一候选应包含“方均根”，证明 `shulihua` 已直接导入。
6. 输入 `shangshangsaiji`，确认腾讯词库能给出“上上赛季”。
7. 输入 `uUhuohuohuo`，应得到“焱 yàn、㷋 tán、燊 shēn、燚 yì、歘 chuā”；
   两套注音均缺失时只在 `uU` 候选显示 `n/a`。
8. 输入 `uuid`、`cC1+1`、`kmjgx`，分别验证 UUID、计算器和颜文字。
9. 主键盘 Enter 和数字小键盘 Enter 都能直接上屏未转换的英文拼音。
10. 验证迁移前记录的个人词条、私有短语、候选数量、字体、主题和布局。
11. 停止输入约 0.5 秒后出现 `☁搜`/`☁谷`，网络查询期间本地按键无卡顿。

`∞` 只标记 Rime 类型为 `sentence` 的模型整句，不是所有受模型调序的普通词都会
显示该符号。云候选与本地/用户/模型同文时，保留无云标记的本地版本。

## 八、额外私有词库

本 Fork 已包含腾讯、维基词典、网络用语、维基文库、维基百科、萌娘百科、颜文字
和全部细胞词库，不要重复导入。只处理盘点中发现、仓库确实没有的 Windows 私有
词库：

1. 从 `$legacy` 读取其词典头、编码格式和原引用；
2. 复制到明确的本地专用文件名；
3. 普通全拼词库才加入 `rime_ice.dict.yaml/import_tables`；独立编码/Lua 方案保持
   独立 translator，不强塞进主词典；
4. 部署后用该词库唯一词条验收；
5. 私有内容不推送到公共 Fork。

跨平台公开词应提交 `custom_phrase_shared.txt` 或合适的公开词典，再按
`Mac -> Windows` 传播；账号、手机号、内部名称只能留在私有覆盖层。

## 九、隐私说明

万象模型完全在本地运行。云拼音会把当前尚未上屏的全拼编码通过 HTTPS 分别发送
给搜狗和 Google Input Tools；第三方会获得网络请求固有的 IP、时间和 User-Agent。
本项目不会主动发送用户词典、本地候选、已上屏正文、剪贴板或主题文件。

helper 会在用户目录保存 request、response、heartbeat 和 log。它们可能暂时包含
当前编码或云候选，不得提交。不能接受输入编码发送给第三方时，从
`rime_ice.custom.yaml` 删除三个 `cloud_pinyin_async` 组件并重新部署。

## 十、回滚与清理

任一核心验收失败时，先保留日志、`$legacy` 和 `$backup`。完整回滚：

```powershell
& $weaselServer.FullName /q
Start-Sleep -Seconds 2
$failed = "$rimeUser.failed-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Move-Item -LiteralPath $rimeUser -Destination $failed
New-Item -ItemType Directory -Path $rimeUser | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($backup, $rimeUser)
& $weaselDeployer.FullName /deploy
Start-Process -FilePath $weaselServer.FullName
```

不要覆盖 `$backup` 或删除 `$failed`，直到用户确认原方案和个人词条已恢复。

只有全部验收通过并经用户确认后，才可以：

- 删除临时 `$stage`；
- 将 `$legacy` 移出活动磁盘或删除（完整 ZIP 仍应保留）；
- 清理旧的 Frost 导出文本。

## Agent 最终报告模板

```markdown
# Windows 雾凇迁移结果

- rime-ice commit：...
- cloud helper commit：...
- Rime 用户目录：...
- 小狼毫 / librime 版本：...
- 用户词典工具：`scripts/rime_userdb_tool.py` / 其他；导出、导入记录数：...
- 备份 ZIP：...；条目数：...；大小：...
- 万象资产更新时间 / 大小 / SHA-256：...
- Frost 学习键：...；Ice 合并后键：...；缺失：0
- `build/rime_ice.schema.yaml` 检查：通过 / 失败
- 本地、万象、云拼音、分段回退、拆字、腾讯、细胞、私有词：逐项结果
- UI 字体、主题、候选数量：保持 / 差异
- 旧目录：保留路径 / 已经用户确认后清理
- 未执行或仍需人工确认：...
```

官方资料：[雾凇拼音](https://github.com/iDvel/rime-ice)、
[小狼毫](https://github.com/rime/weasel)、
[万象模型 LTS](https://github.com/amzxyz/RIME-LMDG/releases/tag/LTS)、
[异步云拼音](https://github.com/skykeyjoker/rime-cloud-pinyin-async)。
