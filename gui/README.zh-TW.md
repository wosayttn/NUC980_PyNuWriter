# NuWriter Desktop GUI

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主手冊](../README.zh-TW.md) | [範例檔案](../sample/README.zh-TW.md) | [驅動程式](../driver/README.zh-TW.md)

## 安裝與啟動

開啟[下載頁面](https://github.com/wosayttn/NUC980_PyNuWriter/actions)，選取已完成的項目，再從 **Artifacts** 下載符合系統的 GUI 套件（需登入 GitHub）。
解壓兩層壓縮檔，保留完整目錄，包括 `backend`。
Windows 開啟 `nuwriter-gui.exe`，Linux 開啟 `nuwriter-gui`，macOS 開啟 `nuwriter-gui.app`。
macOS 的 app 與 `backend` 須放在同一目錄。

使用原始碼時，先完成[驅動程式與系統相依套件安裝](../README.zh-TW.md#從原始碼安裝)，再於 `NUC980_PyNuWriter` 執行：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

GUI 需要桌面環境。獨立版不需安裝 Python。

## 連接板子

1. 將板子設為 USB Boot 模式，連接 USB Device 埠與電腦。
2. 選擇板子的 **DDR Init** 設定，按 **Refresh** 列出裝置。
3. 選擇 **USB Device**；只接一張板子時可用 **Auto**。
4. 按 **Re-Connect**。板子重置或重新上電後須再次執行。

**Re-Connect 可能透過 CH341 重置板子。** 未使用該轉接器時，請手動重置至 USB Boot 模式。
DDR 設定取自 `sys_cfg`，請選擇符合板子的檔案。

## 燒錄、讀取與擦除

1. 在 **Choose type** 選擇 **SPI NAND**、**SPI NOR**、**NAND** 或 **SD/eMMC**。
2. 按 **Browse** 加入映像並選取該列，再選擇 **Data**、**Environment**、**Loader** 或 **Pack**。
3. 輸入起始位移；Loader 另需輸入執行位址。
4. 按 **Program**。若要驗證寫入資料，先勾選 **Program + Verify**。

**Program 只燒錄選取列。** 位移與長度單位為 byte，請輸入 `0x100000` 等十六進位數值。
Loader 起始位移：Flash 為 `0x0`，SD／eMMC 為 `0x400`。

| 控制項 | 操作 |
| --- | --- |
| Verify | 讀回並比較 Data 映像，不燒錄 |
| Read | 將指定範圍或整顆裝置儲存成檔案 |
| Erase | 擦除所有良好區塊或指定的對齊範圍 |
| Format | 重設 SD／eMMC 分割區；大小單位為 MiB，最後一區使用剩餘空間 |

Loader、Environment 與 Pack 請使用 **Program + Verify**。
SPI NOR 全區讀取須指定容量，單位為 bytes。

**Erase 與 Format 會刪除資料，請先備份。** SD／eMMC 不支援 Erase。
操作逾時後，請先檢查或重置板子再重新連接。
操作完成後才能關閉程式，設定會在離開時儲存。

## SDRAM

選擇 **SDRAM**、映像與載入位址，再選 **Download only** 或 **Download and run**。
勾選 **DTB file** 可指定 DTB 與位址；勾選 **Bootargs** 後輸入核心參數。
直接執行 Linux 核心時，請使用 `zImage`，不可使用 `uImage`，並搭配相符的 DTB／rootfs。
下載至 RAM 不會燒錄 Flash，但板子啟動的軟體可能寫入 Flash。

## 產生與燒錄 Pack

1. 選擇 **Pack**，開啟[範例設定](../sample/README.zh-TW.md)或自備 JSON。
2. 以 **Add**、**Modify**、**Delete** 編輯映像清單；**Save JSON** 儲存設定。
3. 指定輸出路徑並按 **Output** 產生 Pack，不需連接板子。
4. 選擇目標 Flash 類型，將產生的檔案設為 **Pack**，再按 **Program**。

相對映像路徑以 JSON 所在目錄為準。燒錄前請確認所有位移、DDR 與 Flash 設定。
使用範例時，請保留原始碼 ZIP 中相鄰的 `sample` 與 `sys_cfg` 目錄。
單板 Pack 燒錄不會自動執行全裝置擦除。
Pack 驗證不比較 Loader 標頭／DDR 資料、SD 分割區設定、OOB 或未使用區域。

## 量產

1. 將所有板子設為 USB Boot 模式，連接其 USB Device 埠。
2. 選擇 **Mass Production**、DDR 設定與目標媒體，按 **Re-Connect**。
3. 選擇 Pack 並開始燒錄，檢查各裝置的 **Erase**、**Burn**、**Verify** 與最終結果。

**NAND／SPI NAND 量產會先擦除所有良好區塊再燒錄。** SPI NOR 與 SD／eMMC 不另做全裝置擦除。
各板依序處理；失敗不重試，後續板子仍繼續。

## Console 與紀錄

- **Console**：選擇偵錯 UART 與鮑率，按 **Open**；預設為 115200、8N1。變更串口或鮑率前先按 **Close**。隱藏視窗仍保持連線，關閉視窗才釋放串口。
- **USB Trace**：顯示視窗開始記錄 USB 傳輸，隱藏即停止。`<H->D>` 為電腦到板子，`<D->H>` 為板子到電腦。紀錄可能包含映像內容，分享前請先檢查。
- **Op. log**：查看指令、進度與錯誤，再按同一按鈕隱藏。文字可選取與複製。