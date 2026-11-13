# NUC980 PyNuWriter

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

跨平台的 NUC980 命令列工具與桌面 GUI，支援下載至 RAM、燒錄 NAND／SPI Flash，
以及燒錄 SD／eMMC。互動操作請參閱[桌面 GUI 指南](gui/README.zh-TW.md)，
命令列操作則可依照下列範例進行。

## 下載獨立執行版本

獨立封裝的 CLI 與 GUI 不需要另外安裝 Python。

請選擇符合使用作業系統與架構的 CLI 或 GUI 套件。

| 平台 | CLI artifact | GUI artifact |
| --- | --- | --- |
| Windows x64 | `nuwriter-cli-windows-x64` | `nuwriter-gui-windows-x64` |
| Linux x64 | `nuwriter-cli-linux-x64` | `nuwriter-gui-linux-x64` |
| macOS Intel | `nuwriter-cli-macos-x64` | `nuwriter-gui-macos-x64` |
| macOS Apple Silicon | `nuwriter-cli-macos-arm64` | `nuwriter-gui-macos-arm64` |

每個 artifact 包含應用程式壓縮檔與 `.sha256` 校驗檔。先解壓下載的 artifact，
再解壓其中的 `.zip`（Windows）或 `.tar.gz`（Linux／macOS）。
請保留完整應用程式目錄，包括 `_internal` 與 `backend`；此版本採自包含目錄，
不是單一檔案封裝。GUI 已內含 CLI backend，不需要另外下載 CLI。

macOS 解壓後的 `nuwriter-gui` 目錄內包含 `nuwriter-gui.app` 與同層的 `backend`。
請保留兩者，移動時須移動整個目錄，不要只取出 `.app`。

GUI 請開啟 `nuwriter-gui.exe`、`nuwriter-gui` 或 `nuwriter-gui.app`。
若使用下方 CLI 範例，請在解壓後的 `nuwriter` 目錄，將 `python nuwriter.py`
改為 Windows 的 `.\nuwriter.exe` 或 Linux／macOS 的 `./nuwriter`。
封裝內含 DDR／XUSB 資源與第三方授權文件，但不包含大型範例映像，
請另外從此 repository 下載範例檔案。

Windows 仍需安裝 [NUC980 WinUSB 驅動程式](driver/README.zh-TW.md)；安裝程式位於
CLI 的 `_internal/driver`（GUI 封裝內則位於 `backend/nuwriter` 下）。
Linux 仍需 USB／串口權限與原生函式庫，Debian／Ubuntu 可執行：

```bash
sudo apt-get install -y libusb-1.0-0 libegl1 libgl1 libxkbcommon0 libxcb-cursor0 libdbus-1-3 fonts-noto-core
```

macOS 請安裝與執行檔架構相同的 libusb：

```bash
brew install libusb
```

Linux 套件需要 Ubuntu 22.04 或相容的 glibc 系統。macOS 套件以 macOS 15 為目標，
更舊版本尚未驗證。套件沒有開發者簽章或公證，Windows／macOS 可能顯示
安全警告；開啟前請確認來源與校驗碼。

## 從原始碼安裝

命令列工具需要 Python 3.9 以上版本及 libusb-1.0。CI 使用 Python 3.14；
GUI 請使用 PySide6 支援的 Python 版本。下列命令均從此 repository 目錄執行。
請保留程式旁的 `sys_cfg`、`xusb`、`driver` 與 `sample` 目錄，
並讓 CLI 與 GUI 使用相同的虛擬環境。

### Windows

內附 libusb DLL 為 x64 版本，請安裝 x86-64 Python。在 PowerShell 執行：

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

```bash
python -m pip install -r requirements.txt
```

依照[驅動程式指南](driver/README.zh-TW.md)安裝 NUC980 WinUSB 驅動程式。
請選擇板子的 USB Device 介面，不要選擇除錯 VCOM 或 CH341 轉接器。
NuWriter 在存取 USB 前會將內附 DLL 目錄加入目前程序的 PATH，
不會修改永久 PATH。只有使用選配的 CH341 自動重置轉接器時，
才需要安裝其驅動程式。

### Linux

以下以 Debian／Ubuntu 為例；其他發行版請安裝對應套件：

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y python3 python3-venv python3-pip libusb-1.0-0
```

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
```

桌面 GUI 常用的 Qt 系統套件如下：

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libxcb-cursor0 fonts-noto-core
```

請透過裝置權限授予 USB 存取權。若使用已登入的本機桌面工作階段，
可將下列規則放入 `/etc/udev/rules.d/70-nuvoton-nuwriter.rules`：

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5963", TAG+="uaccess"
```

```bash
sudo udevadm control --reload-rules
```

重新插拔板子。無桌面或遠端使用者可能需要改用以群組為基礎的規則。
串口權限需另外設定；Debian／Ubuntu 常使用 `dialout` 群組。
不要將 CH341 串口驅動程式替換為 USB 燒錄驅動程式。

### macOS

透過 [Homebrew](https://brew.sh/) 安裝 Python 與 libusb：

```bash
brew install python@3.14 libusb
```

```bash
"$(brew --prefix python@3.14)/bin/python3.14" -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
```

Python 與 libusb 必須使用相同架構（arm64 或 x86_64）。
Linux／macOS 使用系統的 libusb，不使用 Windows DLL 或 WinUSB 安裝程式。

## 桌面 GUI

在已啟用的虛擬環境內執行：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

[GUI 指南](gui/README.zh-TW.md)包含 Console、USB Trace、Operation Log、
設定保存與 Mass Production 的操作說明。GUI 需要桌面工作階段。
啟動 GUI 不會自動連線、重置或燒錄板子。

## 範例檔案

範例使用內附的 [sample 檔案](sample/README.zh-TW.md)與 NUC980DK71YC DDR 設定。
使用前請確認板子、DDR、Flash 幾何配置與開機媒體；
範例配置並非適用所有板子的通用預設值。

| 範本 | Backend 模式 | 根檔案系統 |
| --- | --- | --- |
| [SPI NAND](sample/config_spinand.json) | `spinand` | UBI，位於 0x800000 |
| [SD1](sample/config_sd1.json) | `sd` | ext4，位於 0x800000 |

SD1 是板子的操作流程名稱，不是獨立的 CLI 模式。
SD1 範本保留 8 MiB 空間，並建立使用記憶卡剩餘容量的分割區。
其分割紀錄與預先產生的 SD pack 所使用的原始 MBR 不同。
RAM 執行 raw kernel 請使用 `zImage`；Flash pack 範本使用帶有 U-Boot header 的 `uImage`。
離線檢查通過不代表已成功開機。

## 連線

1. 將板子設定為 USB Boot 模式並上電。
2. 將板子的 USB Device 埠連接電腦，不要使用 VCOM／除錯埠。
3. 列出裝置並初始化 DDR／XUSB：

```bash
python nuwriter.py --list
```

```bash
python nuwriter.py -a NUC980DK71YC.ini
```

重置或重新上電後，請再次初始化。下列後續命令使用已執行中的 XUSB。
`--ddr` 只提供 DDR 設定，不會執行初始化。

**自動重置：**若有 `pre-attach-hook.py`，`-a` 會在連線前執行它。
內附 hook 偵測到 CH341 時會透過它重置板子。沒有 CH341 轉接器時，
會顯示提示並略過自動重置；請先手動重置板子進入 USB Boot 模式。
若偵測到轉接器，但開啟或控制失敗，操作仍會中止。
離線檢查與 pack 產生不會重置板子。獨立的 reset helper 未找到 CH341 時，
會回傳 exit code 3。

## 燒錄與讀取 Flash

將主 U-Boot 寫入位元組位址 `0x100000`，並驗證資料：

```bash
python nuwriter.py -w spinand 0x100000 sample/u-boot-spinand.bin -o verify
```

讀回 `0x20000` bytes 至檔案：

```bash
python nuwriter.py -r spinand 0x100000 0x20000 readback.bin
```

上述燒錄只安裝主 U-Boot，不包含 SPL、environment、kernel 或 rootfs。
讀取操作會建立或覆寫輸出檔案。讀取整個裝置可使用：

```bash
python nuwriter.py -r spinand all backup.bin
```

SPI NOR 的全裝置讀取還需要以 `--flash-size` 提供位元組容量。
一般讀取不包含 OOB／壞區塊標記，不能視為實體晶片每個位元組的完整備份。

**Erase All 會刪除 Flash 內容，請先備份需要保留的資料。**
NAND／SPI NAND 擦除會略過已標記的壞區塊，並保留其標記：

```bash
python nuwriter.py -e spinand all
```

更新 UBI 映像前，需清除整個 rootfs 區域中的舊 UBI 區塊。
燒錄較短的映像不會清除未寫入的尾端區塊。
Erase All 也會移除 boot loader 與可寫入的檔案系統，請先備份。

請將 `spinand` 替換為所需媒體。位址與長度單位皆為 bytes，
十六進位值使用 `0x` 前綴。

| 媒體 | 寫入起始位址對齊 | 讀取起始位址對齊 | 擦除 |
| --- | --- | --- | --- |
| `nand`、`spinand` | Flash 區塊 | Flash 區塊 | 完整區塊 |
| `spinor` | 4 KiB | 64 KiB | 64 KiB 單位 |
| `sd`、`emmc` | 512 bytes | 512 bytes | 不支援 |

## 下載至 RAM

將板子的主 U-Boot 載入其連結位址並執行：

```bash
python nuwriter.py -w ddr 0x00e00000 sample/u-boot-spinand.bin -o execute
```

省略 `-o execute` 即只下載、不執行。Linux 可同時下載 kernel 與 DTB；
下列範例使用已安裝的 SPI NAND rootfs：

```bash
python nuwriter.py -w ddr 0x8000 sample/zImage -o execute --dtb sample/nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M"
```

請使用相符的 kernel、DTB 與已安裝的 rootfs。
sample 的 `uImage` 帶有 U-Boot header，不能直接當作 raw kernel 執行；
此 RAM 流程應使用 `zImage`。`--bootargs` 只修改下載至 RAM 的 DTB 副本。
RAM 下載不會燒錄 Flash，但啟動後的作業系統可能會寫入 Flash。
下載與燒錄進度以 10% 為間隔顯示；100% 不代表下載的軟體已成功開機。

## 建立與燒錄 Pack

使用 [SPI NAND](sample/config_spinand.json) 或 [SD1](sample/config_sd1.json) 範本。
CLI 的映像相對路徑是依目前工作目錄解析，因此請從 `sample` 執行這些設定。
GUI 會自動處理這個執行目錄。

```bash
cd sample
```

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_sd1.json --check
```

離線檢查不會重置、存取板子或寫入輸出檔案。
產生 pack 時省略 `--check`；下列命令會覆寫指定的 sample pack 檔案：

```bash
python ../nuwriter.py -p config_spinand.json
```

```bash
python ../nuwriter.py -p config_sd1.json
```

```bash
cd ..
```

JSON 的 `mode` 接受 `nand`、`spinand`、`spinor`、`sd` 或 `emmc`。

| 映像 `type` | 用途 |
| --- | --- |
| `data`、`linux` | 原樣保存檔案內容 |
| `loader` | Boot loader，需 DDR 設定與正確的進入位址 |
| `env` | U-Boot environment 文字檔 |
| `partition` | SD／eMMC 分割設定 |

SPI loader 還需要 Flash 命令參數；SPI NAND 需要 page 與 spare 大小。
請使用實際晶片的設定，不要套用其他媒體的參數。

初始化後，燒錄產生的 pack：

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini
```

單板操作如需擦除，請另外執行。加入 `-o verify` 可在燒錄後比對 pack 映像資料：

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

```bash
python nuwriter.py -w sd sample/nuwriter-pack-sd.bin --ddr NUC980DK71YC.ini -o verify
```

單板 Pack 燒錄不會自動增加 Erase All。
Pack Verify 比對映像資料，不包含 loader header／DDR bytes 與 SD 分割指令。
Loader 必須是第一個映像，位於 offset 0（Flash）或 0x400（SD／eMMC）。
SPI NOR Pack Verify 要求 offset 對齊 64 KiB；不會驗證未使用區域或 OOB。

## 量產模式

先手動將每張板子重置至 USB Boot 模式，再初始化所有已連接的板子：

```bash
python nuwriter.py -m -a NUC980DK71YC.ini
```

執行完整的逐板循序流程：

```bash
python nuwriter.py -m -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

**NAND／SPI NAND 會先執行 Erase All，再進行 Burn／Verify。**
這會刪除既有 boot、environment 與檔案系統資料，並保留已標記壞區塊。
SPI NOR 與 SD／eMMC 不執行獨立的全裝置擦除。
每張板子會回報階段與結果；失敗不會自動重試，也不會阻止後續板子繼續處理。
整批結束後，若有任一板失敗，程序會回傳非零 exit status。
若未加入 `-o verify`，CLI 的 `-m` 燒錄仍會循序逐板執行，但不會自動增加 Erase All。
目前並非並行燒錄，GUI 會顯示每板的個別階段與結果。

## 離線檢查與疑難排解

加入 `--check` 可驗證輸入，不會重置、存取板子或寫入輸出檔案。
此檢查不會確認已連接 Flash 的實際容量或幾何配置。

```bash
python nuwriter.py -a NUC980DK71YC.ini --check
```

多板連接時，可使用 `--list` 取得的路徑搭配 `--device` 選擇單一裝置。
USB 診斷可加入 `--trace-usb`；紀錄包含裝置路徑，也可能包含映像資料。
GUI 的 USB Trace 視窗只有顯示時才會側錄。
`--timeout` 與 `--operation-timeout` 的單位為毫秒。
擦除逾時時不要繼續燒錄；請等待板子停止操作，再重新初始化。

若 macOS 找不到 Homebrew libusb，請先在目前終端設定搜尋路徑，再啟動 CLI／GUI：

```bash
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix libusb)/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/usr/lib}"
```

## 測試

GitHub Actions 會在 push、pull request 與手動執行時，使用 Python 3.14
於 Windows、Ubuntu 與 macOS 執行 backend 及 offscreen GUI 測試。
請將測試與 sample fixture 一併提交。
測試使用模擬裝置或真實 sample 映像的離線檢查，不會連接板子。
執行兩套測試前，請先安裝 GUI requirements。

```bash
python -m unittest discover -s . -p test_nuwriter.py -v
```

```bash
python -m unittest discover -s gui -p test_gui.py -v
```

Windows batch 整合測試需要同層的 `numaker-iot-nuc980g2` 目錄；
單獨 checkout 沒有此目錄時會略過該組測試。
原生桌面顯示與實體板操作仍需要手動測試。

## 授權

專案自有的 Python 原始碼與文件採用
[Apache License, Version 2.0](LICENSE)。

內附 libusb 採 LGPL-2.1-or-later，詳見[驅動程式指南](driver/README.zh-TW.md)。
第三方軟體、WinUSB 安裝程式、XUSB 韌體與 DDR 設定檔保留各自的原始授權與著作權，
不會因本專案而改變其授權。

獨立發行包包含第三方聲明、GPL／LGPL 正文、對應版本的函式庫原始碼封存檔，
以及可重建的應用程式原始碼。再次散布時，請保留 `licenses/` 與 `sources/`。
發行包排除 Qt Virtual Keyboard 及其外掛；pyte 保留為可替換的 Python 原始碼。
詳見[再次散布與替換說明（英文）](licenses/README.md)。
散布者仍須對其散布條件進行法務審查。