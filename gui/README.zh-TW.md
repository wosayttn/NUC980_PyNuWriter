# NuWriter 桌面 GUI

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主使用指南](../README.zh-TW.md) | [範例指南](../sample/README.zh-TW.md) | [驅動程式指南](../driver/README.zh-TW.md)

既有 NuWriter backend 的跨平台 Qt 前端。主要配置包含 Choose type、DDR Init、
Re-Connect、映像清單、Parameters 與操作按鈕。Backend 以獨立 Python 程序執行。

## 安裝與啟動

從 `NUC980_PyNuWriter` 目錄，使用你的 Python 環境執行：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

Linux／macOS 如有需要可使用 `python3`。PySide6 需要桌面工作階段；Linux 也需要
系統 libusb 與 Qt 平台函式庫。Debian／Ubuntu 若出現缺少 xcb cursor 函式庫的訊息，
請安裝 `libxcb-cursor0`。Windows 需要 NUC980 WinUSB 驅動程式；內附 DLL 需要 64-bit Python。

GUI 與 backend 使用相同的 Python interpreter。啟動 GUI 不會開啟串口、掃描 USB、
重置板子或寫入 Flash。主視窗從螢幕可用區域左上角開始顯示，沒有 Help 選單。
更新後請重新安裝 GUI requirements，包含 ANSI 終端處理所需的 `pyte`。

## 串口 Console

**Console**、**USB Trace** 與 **Op. log** 位於 USB Device 列的 **Refresh** 右側，
靠右排列，backend 操作期間仍可使用。點選 **Console** 顯示或隱藏 Console 視窗。
Port 清單、baud rate、Refresh 與 **Open** 都位於該視窗內。
請選擇板子的除錯 UART／VCOM，而非 CH341 重置轉接器，再按 **Open** 連線。
顯示視窗不會自動開啟串口；插拔轉接器後請重新整理清單。

首次沒有幾何紀錄時，Console 與主視窗同大小，顯示在右側並對齊上緣。
之後隱藏或關閉會保留位置與大小；重開時還原，不再跟隨主視窗移動或縮放。
幾何資訊也會存入設定，供下次 APP 執行還原。原螢幕不存在時 Qt 可能調整位置；
Wayland 也可能覆寫視窗位置。終端不顯示水平／垂直捲軸，可用滑鼠滾輪查看歷史；
新輸出會回到最新文字。

黑底終端接收 UART 輸出，並直接接受鍵盤輸入。預設為 115200 baud、8 data bits、
無 parity、1 stop bit、無 flow control。Enter 送出 CR，方向鍵送終端控制序列，
Ctrl+C 在未選取文字時送出 interrupt；若已選取文字則複製。
輸入沒有本機 echo，顯示內容由板子決定。貼上多行文字需要確認。

只使用一個 Console 視窗／連線。以 **Console** 隱藏視窗會保留連線與輸出，重開保留歷史。
連線按鈕未連線時為 **Open**，成功連線後為 **Close**。更換 port／baud 前請先按 **Close**。
開啟失敗、關閉或裝置移除後會回到 **Open**。
關閉 Console、在終端輸入區外按 Esc，或關閉主視窗，會釋放串口。
Backend 操作期間仍可使用 Console。

ANSI 前景／背景支援標準與亮色、256 色、RGB，以及粗體、斜體、底線、刪除線、
反白與顏色重置；`pyte` 也處理游標移動與清除。
Console 沒有 Save／Clear 按鈕，但可選取與複製文字。
開啟前會要求 DTR／RTS 為非作用狀態；部分轉接器／驅動程式仍可能產生脈衝，請確認接線。

## USB Trace

**Console** 旁的 **USB Trace** 按鈕可顯示或隱藏 Trace 視窗。
顯示時啟用側錄；隱藏或關閉時停用側錄、backend trace 格式化及 GUI trace 處理。
操作執行中也會生效，不重啟 backend 或中斷 USB 傳輸。

Trace 顯示在主視窗右側、上緣對齊，跟隨主視窗移動／縮放，但保留自身大小。
它留在主視窗所在螢幕；空間不足時可能重疊。Wayland compositor 可能覆寫要求的位置。

Trace 只進入此視窗；命令、進度與錯誤保留在 Operation Log。
Trace 使用黑底彩色等寬文字。`<H->D>` 表示 host 到 device，`<D->H>` 表示 device 到 host。
每筆交易以前面的 USB bus／port 路徑識別裝置，例如
`[2:4.2.2] <H->D> CONTROL OUT request=0xb0 value=0x0080 index=0 length=0`。
Bulk endpoint 位址仍位於 `endpoint=`；沒有裝置路徑資訊的紀錄不加該前綴。
不顯示 `data=`。資料從次行開始，每行 16 bytes，首字對齊交易名稱 `BULK`／`CONTROL`。
縮排依裝置路徑與方向前綴調整，沿用交易顏色；截斷時 `...` 獨立顯示在同縮排的一行。

| 交易 | 前綴 | 顏色 |
| --- | --- | --- |
| CONTROL OUT | `<H->D>` | 藍 |
| CONTROL IN | `<D->H>` | 青 |
| BULK OUT | `<H->D>` | 黃 |
| BULK IN | `<D->H>` | 綠 |

隱藏／關閉保留既有內容，但不新增紀錄。只使用一個 Trace 視窗，操作期間按鈕仍可用。
保留最新 10,000 行，新輸出會捲到最新項目。文字可選取複製；紀錄可能包含映像或讀回資料，
分享前請先檢查。

## 燒錄 Flash

1. 準備 USB Boot 模式並連接 USB Device 埠。
2. 選擇板子的 DDR Init，以 Refresh 列出目標；單板也可保持 Auto。
3. 按 Re-Connect 初始化 DDR／XUSB，會執行 pre-attach reset hook。
4. 選擇 SPI NAND、SPI NOR、NAND 或 SD／eMMC，選檔並設定 Data、Environment、Loader 或 Pack。
5. 設定映像起始 offset／execute address，再按 Program。

DDR Init 只列出專案相對 `sys_cfg` 目錄的 INI，不能瀏覽外部 DDR 檔案。
路徑依專案位置解析，不依目前工作目錄。位址與 read／erase 長度單位皆為 bytes，
十六進位使用 `0x`。Loader 需要正確 DDR 與連結進入位址；Flash offset 為 0，
SD／eMMC 為 `0x400`。每個操作會先離線檢查，失敗不會開始真正操作。
Save JSON 則直接寫入設定檔。

## 操作

| 操作 | 行為 |
| --- | --- |
| Program | 只燒錄選定列，目的地既有資料可能被覆寫 |
| Program + Verify | 燒錄一個映像，再由 backend 讀回驗證 |
| Verify | 只讀回 Data 映像並比對，不燒錄 |
| Read | 保存指定範圍或整個裝置至檔案 |
| Erase | 確認後擦除所有好區塊或對齊範圍 |
| Format | 僅 SD／eMMC，替換分割／format 資料並重新初始化 DDR／XUSB |

獨立 Verify 僅支援 Data；Loader／Environment 使用 Program + Verify，Pack 也支援此選項。
Read／Verify 遵守 backend 的讀取對齊要求，SPI NOR 包含 64 KiB。
SD／eMMC Format 使用 MiB，最後一個分割區使用剩餘容量。
Format／Erase 會刪除資料，中斷後無法復原已寫入或擦除的資料；重新連線前請確認或重置板子。
操作完成後，可由標題列關閉按鈕離開。

## SDRAM

選擇 SDRAM、映像與位址，再選 Download only 或 Download and run。
啟用 DTB file 可提供 DTB／位址；bootargs 只修改下載的 DTB 副本。
RAM 執行後的軟體可能存取 Flash，傳輸完成不代表成功開機。

## Pack

Pack 可開啟／編輯 JSON。Add、Modify、Delete 修改映像表格，Save JSON 保存設定。
`ddr_ini`、`page_size` 與 SPI 命令等 loader 參數放在 Additional JSON parameters；
SD／eMMC 分割紀錄使用 backend 相同欄位。

Output 不連板，只產生 pack；使用編輯後設定的暫存快照，不會修改已開啟的 JSON。
映像／DDR 相對路徑依設定檔目錄解析；Save JSON 保留該目錄，避免相對路徑改變意義。
操作完成或取消後刪除快照。

Mass Production 會循序處理目標，每板先檢查，再 Erase、Burn、Pack Verify。
NAND／SPI NAND 先 Erase All，保留壞區塊標記，但刪除既有 boot、environment 與檔案系統。
SPI NOR／SD／eMMC 略過獨立的全裝置擦除。Re-Connect 仍循序初始化所有板子。
結果表格按 USB 裝置路徑顯示 Erase／Burn／Verify／最終結果。
一板失敗不重試，後續板子繼續；任何失敗會使整批失敗。
非法 Pack／DDR 設定在燒錄前拒絕。目前沒有並行燒錄或自動 reset／retry；開始 MP 前請備份。

Pack Verify 使用韌體 action 7 讀回映像；比對不包含 loader header／DDR 與 SD 分割指令。
Loader 必須是第一個映像，offset 為 0（Flash）或 0x400（SD／eMMC）；
SPI NOR offset 必須對齊 64 KiB。Verify 只涵蓋 pack 映像資料，不是所有實體／OOB 或未使用區域。

## 設定保存與輸入驗證

關閉 APP 會在 Qt 使用者設定目錄（`QStandardPaths.AppConfigLocation`）保存 `settings.json`。
Windows 通常為 `%LOCALAPPDATA%/NUC980 PyNuWriter`；Linux 通常為
`~/.config/NUC980 PyNuWriter`，或 `XDG_CONFIG_HOME` 指定的目錄。

JSON 保存 media／DDR／USB target、映像清單與選取列、各頁欄位／選項、Pack 草稿／路徑、
彈窗預設值、Console port／baud 及視窗大小。DDR 仍限內附 `sys_cfg`，舊平台設定會移轉 DDR 選項。
不還原 log、連線、執行中操作與彈窗顯示狀態；啟動不會連線或燒錄。

使用原子寫入。非法 JSON 使用預設值，寫入新檔前會備份為 `settings.json.<timestamp>.invalid`。
個別非法值會忽略；保存失敗會提示並保持 APP 開啟，避免默默遺失設定。
位址／長度需 `0x` 加 1 到 8 位十六進位數字（`0x0` 至 `0xffffffff`）。
輸入時拒絕非法字元，未完成或超範圍值不能開始操作；read／erase 長度需非零。
分割數值控制項限制範圍，路徑與 bootargs 拒絕控制字元，來源／輸出路徑使用前檢查。
Pack 額外參數需 JSON object；backend preflight 仍會檢查映像格式、對齊與裝置相關限制。

## Log 與測試

每次 APP 執行第一次開啟 Operation Log，才取得 host OS／kernel、CPU 架構／核心數、
RAM 總量／可用量、Python interpreter、Qt platform、螢幕大小／DPI scale 與設定檔位置。
也透過 package metadata 列出 PySide6、pyte、pyserial、psutil、PyUSB、pyfdt 版本與載入狀態，
不為查版本而載入延後使用的 backend 模組。缺少的硬體資訊標為 unavailable。
主視窗啟動時不查這些資訊，隱藏／重開 log 也不重查；不掃描 USB 或開啟串口。
紀錄保留在 log，不存入設定。

**Op. log** 切換非 modal 視窗，顯示時按鈕保持勾選，只使用一個 log 視窗。
隱藏時仍累積一般輸出，重開保留。視窗在主視窗下方，外框同寬，高度固定 320，
隨主視窗移動／縮放，主視窗離開也會隱藏 log。
標題列為 **NuWriter - Operation Log**，可以拖曳；沒有最小化、最大化、關閉、Save 或 Clear 按鈕。
Esc／Alt+F4 不會關閉，請以 **Op. log** 隱藏；Console 控制項不變。

命令為藍色，一般 backend 結果為綠色；含 `Error`（不分大小寫）的結果列為紅色。
文字可選取／複製，新輸出自動捲到最新。主視窗為 800x560，Flash 控制項保持左右並排。
同時只能執行一個操作。

```bash
python -m unittest discover -s gui -p test_gui.py -v
```

測試使用模擬程序及真正 backend 的離線檢查，不操作硬體。
真實映像整合案例使用 [sample](../sample/README.zh-TW.md) 中的檔案與 SPI NAND／SD1 範本；
請隨測試一併提交素材，離線檢查不寫入 pack 輸出。
Windows 顯示／離線流程已檢查；Linux／macOS 與實體板 GUI 操作仍需平台測試。
GUI 不支援 raw／OOB 燒錄或自訂裝置幾何配置，不啟動 Windows executable，也不修改 backend 原始碼。