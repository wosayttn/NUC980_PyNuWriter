# Windows 驅動程式

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主使用指南](../README.zh-TW.md) | [GUI 指南](../gui/README.zh-TW.md) | [範例指南](../sample/README.zh-TW.md)

## NUC980 USB 驅動程式

執行 `WinUSB4NuVCOM.exe` 安裝 NUC980 USB 驅動程式。
請選擇板子的 USB Device 介面，不要選擇除錯 VCOM 或 CH341 串口轉接器。

## CH341 USB 串口驅動程式

只有使用 CH341 轉接器進行串口／重置控制時，才需要安裝此驅動程式。

1. 從 WCH 下載 `CH341SER.EXE`：[英文網站](https://www.wch-ic.com/downloads/CH341SER_EXE.html)或[中文網站](https://www.wch.cn/downloads/CH341SER_EXE.html)。支援 32-bit／64-bit Windows，包含 Windows 10 與 11。
2. 執行安裝程式，再重新連接 CH341 轉接器。
3. 在裝置管理員的 **連接埠（COM 和 LPT）**確認 CH341 串口。

從 `NUC980_PyNuWriter` 目錄列出可用串口：

```bash
python ch341_reset_uart.py --list
```

請使用 USB-serial／VCP 驅動程式，而非 CH341PAR。不要以 WinUSB 取代 CH341 驅動程式；
NUC980 USB 燒錄與 CH341 串口／重置使用不同的驅動程式。

## libusb 執行環境

`libusb-1.0.dll` 是未修改的 libusb 1.0.29 Windows x64 DLL，
取自官方 `VS2022/MS64/dll` build。需要 64-bit Python，不能取代 NUC980 WinUSB 驅動程式。

Windows 上若有此 DLL，工具會在存取 USB 前，將此目錄的絕對路徑加入目前程序的 `PATH`。
不會修改永久的使用者或系統 `PATH`。若 DLL 缺失，則使用既有系統函式庫搜尋方式。

上游版本：https://github.com/libusb/libusb/releases/tag/v1.0.29

DLL SHA-256：

```text
5072054cb3002ae071f382ad5c2c2b0092d9451c537d0c13444c2b6f968f7251
```

## libusb 著作權與授權

著作權屬於 libusb 作者及貢獻者。libusb 採 GNU Lesser General Public License
version 2.1 或更新版本授權，不提供保固，也不屬於本專案的 Apache 授權。

- [授權原文](LICENSE.libusb.txt)：上游原始 COPYING 檔案。
- [作者清單](AUTHORS.libusb.txt)：上游原始貢獻者清單。
- [對應原始碼](libusb-1.0.29.tar.bz2)：完整且未修改的官方原始碼發行包，包含個別檔案的授權聲明及建置腳本。

重新發行此目錄時，請將以上檔案與 DLL 一併保留。
既有 WinUSB 安裝程式保留原始授權及著作權條款。