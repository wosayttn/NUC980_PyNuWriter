# Windows 驱动程序

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主使用指南](../README.zh-CN.md) | [GUI 指南](../gui/README.zh-CN.md) | [示例指南](../sample/README.zh-CN.md)

## NUC980 USB 驱动程序

执行 `WinUSB4NuVCOM.exe` 安装 NUC980 USB 驱动程序。
请选择开发板的 USB Device 接口，不要选择调试 VCOM 或 CH341 串口转接器。

## CH341 USB 串口驱动程序

只有使用 CH341 转接器进行串口／复位控制时，才需要安装此驱动程序。

1. 从 WCH 下载 `CH341SER.EXE`：[英文网站](https://www.wch-ic.com/downloads/CH341SER_EXE.html)或[中文网站](https://www.wch.cn/downloads/CH341SER_EXE.html)。支持 32-bit／64-bit Windows，包括 Windows 10 与 11。
2. 执行安装程序，再重新连接 CH341 转接器。
3. 在设备管理器的 **端口（COM 和 LPT）**确认 CH341 串口。

从 `NUC980_PyNuWriter` 目录列出可用串口：

```bash
python ch341_reset_uart.py --list
```

请使用 USB-serial／VCP 驱动程序，而非 CH341PAR。不要用 WinUSB 替换 CH341 驱动程序；
NUC980 USB 烧录与 CH341 串口／复位使用不同的驱动程序。

## libusb 运行环境

`libusb-1.0.dll` 是未修改的 libusb 1.0.29 Windows x64 DLL，
取自官方 `VS2022/MS64/dll` build。需要 64-bit Python，不能替代 NUC980 WinUSB 驱动程序。

Windows 上若有此 DLL，工具会在访问 USB 前，将此目录的绝对路径加入当前进程的 `PATH`。
不会修改永久的用户或系统 `PATH`。若 DLL 缺失，则使用现有系统库搜索方式。

上游版本：https://github.com/libusb/libusb/releases/tag/v1.0.29

DLL SHA-256：

```text
5072054cb3002ae071f382ad5c2c2b0092d9451c537d0c13444c2b6f968f7251
```

## libusb 版权与许可

版权属于 libusb 作者及贡献者。libusb 采用 GNU Lesser General Public License
version 2.1 或更新版本授权，不提供担保，也不属于本项目的 Apache 许可。

- [许可原文](LICENSE.libusb.txt)：上游原始 COPYING 文件。
- [作者名单](AUTHORS.libusb.txt)：上游原始贡献者名单。
- [对应源代码](libusb-1.0.29.tar.bz2)：完整且未修改的官方源代码发布包，包括各文件的许可声明及构建脚本。

重新发布此目录时，请将上述文件与 DLL 一并保留。
现有 WinUSB 安装程序保留原始许可及版权条款。