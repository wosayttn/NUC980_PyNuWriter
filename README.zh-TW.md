# NUC980 PyNuWriter

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

NUC980 USB 燒錄與 RAM 下載工具。圖形介面操作請參閱 [GUI 手冊](gui/README.zh-TW.md)。

## 下載獨立執行版本

開啟[下載頁面](https://github.com/wosayttn/NUC980_PyNuWriter/actions)，選取已完成的項目，再從 **Artifacts** 下載 CLI 或 GUI 套件（需登入 GitHub）。
選擇 `nuwriter-cli-<platform>` 或 `nuwriter-gui-<platform>`：

| 系統 | Platform |
| --- | --- |
| Windows x64 | `windows-x64` |
| Linux x64 | `linux-x64` |
| macOS Intel | `macos-x64` |
| macOS Apple Silicon | `macos-arm64` |

解壓兩層壓縮檔，保留完整目錄，包括 `_internal` 與 `backend`。
macOS 的 `nuwriter-gui.app` 與 `backend` 須放在同一目錄。獨立版不需安裝 Python。
Windows 需安裝 [NUC980 WinUSB 驅動程式](driver/README.zh-TW.md)；Linux／macOS 需安裝下述 libusb。

GUI 請開啟 `nuwriter-gui.exe`、`nuwriter-gui` 或 `nuwriter-gui.app`。
CLI 請將下列範例的 `python nuwriter.py` 改為 Windows 的 `.\nuwriter.exe`，或 Linux／macOS 的 `./nuwriter`。
Linux 套件以 Ubuntu 22.04 為目標，macOS 套件以 macOS 15 為目標；舊版系統尚未驗證。
套件未經開發者簽章或公證，開啟前請確認來源與 SHA-256。

## 從原始碼安裝

在[原始碼頁面](https://github.com/wosayttn/NUC980_PyNuWriter)選擇 **Code > Download ZIP**，下載後解壓。
下列指令均在含有 `nuwriter.py` 的目錄執行，建議使用 Python 3.14。

### Windows

安裝 64 位元 [Python](https://www.python.org/downloads/windows/) 與 [NUC980 WinUSB 驅動程式](driver/README.zh-TW.md)。
WinUSB 須安裝於板子的 USB Device 介面，勿選偵錯 UART 或重置轉接器。
使用 CH341 時才需安裝其驅動程式。於 PowerShell 執行：

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

### Linux

Debian／Ubuntu 套件，包含 GUI 所需函式庫：

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y python3 python3-venv python3-pip libusb-1.0-0 libegl1 libgl1 libxkbcommon0 libxcb-cursor0 libdbus-1-3 fonts-noto-core
```

本機桌面 USB 權限：建立 `/etc/udev/rules.d/70-nuvoton-nuwriter.rules`，內容如下：

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5963", TAG+="uaccess"
```

```bash
sudo udevadm control --reload-rules
```

重新連接板子。遠端／無桌面環境需另外設定 USB 群組權限。
串口存取可能還需加入 `dialout` 群組。

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

### macOS

安裝 [Homebrew](https://brew.sh/)，再安裝相同架構的 Python 與 libusb：

```bash
brew install python@3.14 libusb
```

```bash
"$(brew --prefix python@3.14)/bin/python3.14" -m venv .venv
```

```bash
source .venv/bin/activate
```

### Python 套件

各系統啟用虛擬環境後，安裝 CLI 相依套件：

```bash
python -m pip install -r requirements.txt
```

GUI 另需安裝套件，再啟動程式：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

## 連接板子

將板子設為 USB Boot 模式，連接板子的 USB Device 埠與電腦。
範例使用 NUC980DK71YC；請選用 `sys_cfg` 中符合板子的 DDR 設定。

```bash
python nuwriter.py --list
```

```bash
python nuwriter.py -a NUC980DK71YC.ini
```

板子重置或重新上電後須再次初始化。**初始化可能透過 CH341 重置板子。** 未使用該轉接器時，請手動重置至 USB Boot 模式。
多板連接時，可加入 `--device BUS:PORT`，路徑由 `--list` 查詢。
下載、燒錄、擦除或產生 Pack 前，可在指令尾端加入 `--check`，只檢查輸入，不存取板子或寫入輸出檔。

## 燒錄、讀取與擦除

範例使用內附的 [sample 檔案](sample/README.zh-TW.md)。請先確認板子的位移與 Flash 設定。
獨立版不含範例；請將原始碼 ZIP 中的 `sample` 複製到 CLI 執行檔旁。
燒錄主 U-Boot 並驗證：

```bash
python nuwriter.py -w spinand 0x100000 sample/u-boot-spinand.bin -o verify
```

讀取指定範圍或整顆 Flash。輸出檔已存在時會覆寫：

```bash
python nuwriter.py -r spinand 0x100000 0x20000 readback.bin
```

```bash
python nuwriter.py -r spinand all backup.bin
```

**全區擦除會刪除開機程式、設定與檔案系統，請先備份。** NAND／SPI NAND 會保留已標記的壞區塊。

```bash
python nuwriter.py -e spinand all
```

依需求替換 `spinand`。位址與長度單位為 byte，十六進位數值須加 `0x`。

| 媒體 | 寫入起點對齊 | 讀取起點對齊 | 擦除單位 |
| --- | --- | --- | --- |
| `nand`, `spinand` | Flash 區塊 | Flash 區塊 | Flash 區塊 |
| `spinor` | 4 KiB | 64 KiB | 64 KiB |
| `sd`, `emmc` | 512 bytes | 512 bytes | 不支援 |

SPI NOR 全區讀取須加上 `--flash-size`，指定容量（bytes）。
讀取與驗證不涵蓋 OOB 或每個實體壞區塊。
替換 UBI 映像前，須擦除舊 rootfs 區域，包含超出新映像長度的尾端。

## 下載至 RAM

下載並執行主 U-Boot；只下載時移除 `-o execute`：

```bash
python nuwriter.py -w ddr 0x00e00000 sample/u-boot-spinand.bin -o execute
```

Linux 範例，rootfs 須已安裝於 SPI NAND：

```bash
python nuwriter.py -w ddr 0x8000 sample/zImage -o execute --dtb sample/nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M"
```

核心、DTB 與 rootfs 須互相搭配。此方式應執行原始 `zImage`，不可直接執行帶 U-Boot 標頭的 `uImage`。
下載至 RAM 不會燒錄 Flash，但板子啟動的軟體可能寫入 Flash。

## 產生與燒錄 Pack

範例設定使用相對路徑。使用獨立版 CLI 時，也須將原始碼 ZIP 的 `sys_cfg` 複製到執行檔旁。
下列 `python ../nuwriter.py` 請改為 Windows 的 `..\nuwriter.exe`，或 Linux／macOS 的 `../nuwriter`，並在 `sample` 目錄執行：

```bash
cd sample
```

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_spinand.json
```

SD1 請改用 `config_sd1.json`，CLI 媒體名稱為 `sd`。
產生 Pack 會覆寫設定中指定的輸出檔。完成後回到工具目錄：

```bash
cd ..
```

初始化後燒錄並驗證 Pack：

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

```bash
python nuwriter.py -w sd sample/nuwriter-pack-sd.bin --ddr NUC980DK71YC.ini -o verify
```

單板 Pack 燒錄不會自動執行全區擦除。
Loader 須排第一，Flash 起點為 `0x0`、SD／eMMC 為 `0x400`；SPI NOR Pack 驗證要求各映像起點對齊 64 KiB。
Pack 驗證不比較 Loader 標頭／DDR 資料、SD 分割區設定、OOB 或未使用區域。

## 量產

所有板子設為 USB Boot 模式並連接後，初始化及燒錄：

```bash
python nuwriter.py -m -a NUC980DK71YC.ini
```

```bash
python nuwriter.py -m -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

**NAND／SPI NAND 會先擦除所有良好區塊再燒錄。** SPI NOR 與 SD／eMMC 不另做全裝置擦除。
各板依序處理，失敗不自動重試，後續板子仍繼續；任一板失敗會回傳非零 exit status。
省略 `-o verify` 也會停用自動全區擦除步驟。

## 疑難排解

- 初始化失敗：確認 DDR 設定、USB Boot 模式、USB Device 埠與驅動程式。
- 逾時後請等待操作停止，檢查或重置板子，再重新連接。
- 加入 `--trace-usb` 可記錄 USB 診斷，紀錄可能包含映像內容。
- `--timeout` 設定 USB／重連等待時間，`--operation-timeout` 設定操作等待時間，單位皆為毫秒。
- macOS 找不到 libusb 時，啟動前先設定路徑：

```bash
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix libusb)/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/usr/lib}"
```

## 授權

專案自有程式：[Apache-2.0](LICENSE)。第三方授權與替換權利：[授權聲明](licenses/README.md)。
再次散布獨立版時，請保留 `licenses/` 與 `sources/`。