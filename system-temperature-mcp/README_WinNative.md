# system-temperature-mcp を Windows ネイティブで動かす

このドキュメントは、`system-temperature-mcp` を **WSL2 ではなく Windows ネイティブの
Antigravity CLI（PowerShell 版）** で動かすためのセットアップ手順です。

---

## なぜ以前は WSL2 でしか動かなかったのか

`get_current_time` ツールが内部で `zoneinfo.ZoneInfo("Asia/Tokyo")` を呼びます。

- **Linux / WSL2** … システムに IANA タイムゾーンデータベース（`/usr/share/zoneinfo`）が
  存在するため、そのまま解決できる。
- **Windows ネイティブ** … OS 標準では IANA tzdb を持たないため、`zoneinfo` は
  `tzdata` パッケージが無いと `ZoneInfoNotFoundError` を送出し、サーバーが起動時に落ちる。

本リポジトリではこれを次の 2 点で解決済みです。

1. `pyproject.toml` に `tzdata`（Windows 限定マーカー付き）を依存として追加。
2. `server.py` に `_japan_timezone()` を追加し、万一 `tzdata` が無くても
   固定 UTC+9（JST は DST 無し）へフォールバックしてクラッシュしないようにした。

温度取得コード自体はもともと Windows（WMI/PowerShell 経由）に対応していましたが、
本対応でさらに **LibreHardwareMonitor の Web サーバー（`data.json`）読み取り**を追加し、
Windows ネイティブでも実 CPU 温度を取得できるようにしています。

---

## 必要なもの

| 項目 | 内容 |
|------|------|
| Python | 3.13（root `.python-version` で固定） |
| uv | パッケージ／実行管理（`winget install astral-sh.uv` 等） |
| Antigravity CLI | Windows ネイティブ版 |
| （温度取得用）LibreHardwareMonitor | 実 CPU/GPU 温度を取得する場合に使用。任意 |

---

## 1. 依存関係のインストール

リポジトリの root（`embodied-agy/`）で:

```powershell
uv sync
```

`tzdata` を含む依存が入ります。

動作確認:

```powershell
uv run --package system-temperature-mcp python -c "from system_temperature_mcp import server as s; print(s.get_current_time())"
```

`今は 2026年...やで。` のように表示されれば tzdata 対応は成功です。

---

## 2. Antigravity CLI への MCP 登録

### 方法 A: プロジェクトの `.agents/mcp_config.json`（同梱済み）

リポジトリ root で `agy` を起動して folder を trust すると、同梱の `.agents/mcp_config.json` が自動で読み込まれます。
パスは環境に合わせて書き換えてください。

```json
{
  "mcpServers": {
    "system-temperature": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\path\\to\\embodied-agy", "--package", "system-temperature-mcp", "system-temperature-mcp"]
    }
  }
}
```

### 方法 B: CLI で登録

```powershell
agy mcp add system-temperature -- uv run --directory "D:\path\to\embodied-agy" --package system-temperature-mcp system-temperature-mcp
```

登録後、`get_current_time` はこの時点で動作します（温度取得は次章）。

---

## 3. 温度センサーの取得

Windows では OS 標準の API から詳細な CPU コア温度を取れないため、
温度取得は次の優先順位で試行します。

| 優先 | ソース | 精度 | 追加要件 |
|------|--------|------|----------|
| 1 | LibreHardwareMonitor / OpenHardwareMonitor の **Web サーバー**（`data.json`） | 高（CPU コア／SSD 等） | LHM を管理者で常駐 |
| 2 | 同 **WMI 名前空間**（`root/LibreHardwareMonitor`） | 高 | LHM を管理者で常駐＋読む側も管理者 |
| 3 | **ACPI サーマルゾーン**（`MSAcpi_ThermalZoneTemperature`） | 低（マザボzone・粗い） | Antigravity CLI を管理者で起動 |

> **推奨は「1. Web サーバー」方式です。** WMI 名前空間は、LHM を管理者で起動しても
> 読み取り側（Antigravity CLI）が非管理者だとアクセスできないことがあります。
> Web サーバー方式は localhost の HTTP 通信なので、**LHM さえ管理者で動いていれば
> Antigravity CLI 自体は管理者でなくても温度を読めます。**

### 3-1. LibreHardwareMonitor のインストール

推奨（winget）:

```powershell
winget install --id LibreHardwareMonitor.LibreHardwareMonitor -e
```

> 依存の PawnIO（カーネルドライバ）を入れるため、**管理者権限の PowerShell** で実行してください。
> ポータブル版（GitHub Releases の `LibreHardwareMonitor.zip`）を任意フォルダに展開する方法でも可。

### 3-2. Web サーバー＋トレイ常駐の設定

LHM を一度起動し、GUI から以下を設定します（次回起動時に config に保存されます）。

- **Options → Remote Web Server → Port** … 既定 `8085`
- **Options → Remote Web Server → Run** … チェック（Web サーバー起動）
- **Options → Start Minimized** … チェック（最小化で起動）
- **Options → Minimize To Tray** … チェック（タスクトレイへ格納）

GUI を使わず `LibreHardwareMonitor.config`（exe と同じフォルダ）を直接編集する場合:

```xml
<add key="listenerPort" value="8085" />
<add key="runWebServerMenuItem" value="true" />
<add key="startMinMenuItem" value="true" />
<add key="minTrayMenuItem" value="true" />
<add key="minCloseMenuItem" value="true" />
```

> config は LHM の**終了時**に上書きされます。直接編集する場合は LHM を閉じてから編集してください。

### 3-3. 管理者権限で起動する

温度センサーの読み取りにはカーネルドライバのロードが必要なため、
**LHM は必ず「管理者として実行」で起動**してください。非管理者で起動すると
センサーが空になり、Web サーバーも温度を返しません。

### 3-4. 動作確認

```powershell
curl http://localhost:8085/data.json
```

JSON が返り、`"Value": "70.0 °C"` のような温度が含まれていれば成功です。
MCP 経由の確認:

```powershell
uv run --package system-temperature-mcp python -c "from system_temperature_mcp import server as s; import json; print(json.dumps(s.get_all_temperatures(), ensure_ascii=False))"
```

---

## 4. LHM を PC 起動時に自動で管理者常駐させる（推奨）

毎回手動で管理者起動するのは手間なので、タスクスケジューラでログオン時に
最上位の特権（管理者）で自動起動させると便利です。

```powershell
# 管理者 PowerShell で実行。パスは実際の LHM の場所に置き換える
$exe = "C:\path\to\LibreHardwareMonitor.exe"
$action    = New-ScheduledTaskAction  -Execute $exe
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -RunLevel Highest
Register-ScheduledTask -TaskName "LibreHardwareMonitor (elevated autostart)" `
  -Action $action -Trigger $trigger -Principal $principal
```

これで次回ログオン以降、LHM が管理者権限＋トレイ常駐で自動起動し、
Antigravity CLI はいつでも温度を読める状態になります。

---

## 5. 設定オプション

| 環境変数 | 既定値 | 説明 |
|----------|--------|------|
| `SYSTEM_TEMPERATURE_LHM_URL` | `http://localhost:8085/data.json` | LHM Web サーバーの URL。ポートを変えた場合に指定 |

`.agents/mcp_config.json` の該当サーバーに `env` で渡せます:

```json
{
  "mcpServers": {
    "system-temperature": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\path\\to\\embodied-agy", "--package", "system-temperature-mcp", "system-temperature-mcp"],
      "env": { "SYSTEM_TEMPERATURE_LHM_URL": "http://localhost:9000/data.json" }
    }
  }
}
```

---

## 6. LHM 無しで使う場合（簡易フォールバック）

LibreHardwareMonitor を入れたくない場合は、**Antigravity CLI 自体を管理者権限で起動**すれば、
ACPI サーマルゾーン（優先度 3）から粗い温度を取得できます。
CPU コアごとの詳細温度は取れませんが、追加ソフト無しで動きます。

---

## トラブルシューティング

| 症状 | 原因と対処 |
|------|-----------|
| `ZoneInfoNotFoundError` | root で `uv sync` を実行し、`tzdata` が入っているか確認。 |
| 温度が「センサーが見つかりません」 | LHM が**管理者で**起動しているか、Web サーバーが Run になっているか、ポートが一致しているかを確認。`curl http://localhost:8085/data.json` で切り分け。 |
| `data.json` は返るが温度が空 | LHM を管理者で起動していない（ドライバ未ロード）。管理者で起動し直す。 |
| WMI 名前空間が見えない | Web サーバー方式（優先度 1）を使う。WMI は権限の都合で読めないことがある。 |

---

## 検証環境

- Windows 11 Pro / Intel Core i5-7300U
- Python 3.13 + uv、LibreHardwareMonitor 0.9.6
- LHM Web サーバー経由で CPU コア温度・SSD 温度の取得、および MCP stdio 経由での
  `get_system_temperature` / `get_current_time` の動作を確認済み。
