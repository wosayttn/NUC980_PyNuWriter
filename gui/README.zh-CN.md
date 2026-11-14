# NuWriter Desktop GUI

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主手册](../README.zh-CN.md) | [示例文件](../sample/README.zh-CN.md) | [驱动程序](../driver/README.zh-CN.md)

## 安装与启动

打开[下载页面](https://github.com/wosayttn/NUC980_PyNuWriter/actions)，选择已完成的项目，再从 **Artifacts** 下载符合系统的 GUI 软件包（需登录 GitHub）。
解压两层压缩包，保留完整目录，包括 `backend`。
Windows 打开 `nuwriter-gui.exe`，Linux 打开 `nuwriter-gui`，macOS 打开 `nuwriter-gui.app`。
macOS 的 app 与 `backend` 须放在同一目录。

使用源代码时，先完成[驱动程序与系统依赖安装](../README.zh-CN.md#从源码安装)，再在 `NUC980_PyNuWriter` 执行：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

GUI 需要桌面环境。独立版不需安装 Python。

## 连接开发板

1. 将开发板设为 USB Boot 模式，连接 USB Device 接口与电脑。
2. 选择开发板的 **DDR Init** 配置，按 **Refresh** 列出设备。
3. 选择 **USB Device**；仅连接一块开发板时可用 **Auto**。
4. 按 **Re-Connect**。开发板复位或重新上电后须再次执行。

**Re-Connect 可能通过 CH341 复位开发板。** 未使用该适配器时，请手动复位到 USB Boot 模式。
DDR 配置取自 `sys_cfg`，请选择符合开发板的文件。

## 烧录、读取与擦除

1. 在 **Choose type** 选择 **SPI NAND**、**SPI NOR**、**NAND** 或 **SD/eMMC**。
2. 按 **Browse** 添加镜像并选中该行，再选择 **Data**、**Environment**、**Loader** 或 **Pack**。
3. 输入起始偏移；Loader 另需输入执行地址。
4. 按 **Program**。如需验证写入数据，先勾选 **Program + Verify**。

**Program 仅烧录选中行。** 偏移与长度单位为 byte，请输入 `0x100000` 等十六进制数值。
Loader 起始偏移：Flash 为 `0x0`，SD／eMMC 为 `0x400`。

| 控件 | 操作 |
| --- | --- |
| Verify | 读回并比较 Data 镜像，不烧录 |
| Read | 将指定范围或整个设备保存为文件 |
| Erase | 擦除所有好块或指定的对齐范围 |
| Format | 重设 SD／eMMC 分区；大小单位为 MiB，最后一区使用剩余空间 |

Loader、Environment 与 Pack 请使用 **Program + Verify**。
SPI NOR 全区读取须指定容量，单位为 bytes。

**Erase 与 Format 会删除数据，请先备份。** SD／eMMC 不支持 Erase。
操作超时后，请先检查或复位开发板再重新连接。
操作完成后才能关闭程序，配置会在退出时保存。

## SDRAM

选择 **SDRAM**、镜像与加载地址，再选 **Download only** 或 **Download and run**。
勾选 **DTB file** 可指定 DTB 与地址；勾选 **Bootargs** 后输入内核参数。
直接执行 Linux 内核时，请使用 `zImage`，不可使用 `uImage`，并搭配匹配的 DTB／rootfs。
下载到 RAM 不会烧录 Flash，但开发板启动的软件可能写入 Flash。

## 生成与烧录 Pack

1. 选择 **Pack**，打开[示例配置](../sample/README.zh-CN.md)或自备 JSON。
2. 用 **Add**、**Modify**、**Delete** 编辑镜像列表；**Save JSON** 保存配置。
3. 指定输出路径并按 **Output** 生成 Pack，不需连接开发板。
4. 选择目标 Flash 类型，将生成的文件设为 **Pack**，再按 **Program**。

相对镜像路径以 JSON 所在目录为准。烧录前请确认全部偏移、DDR 与 Flash 配置。
使用示例时，请保留源代码 ZIP 中相邻的 `sample` 和 `sys_cfg` 目录。
单板 Pack 烧录不会自动执行全设备擦除。
Pack 验证不比较 Loader 头部／DDR 数据、SD 分区配置、OOB 或未使用区域。

## 量产

1. 将全部开发板设为 USB Boot 模式，连接其 USB Device 接口。
2. 选择 **Mass Production**、DDR 配置与目标媒体，按 **Re-Connect**。
3. 选择 Pack 并开始烧录，检查各设备的 **Erase**、**Burn**、**Verify** 与最终结果。

**NAND／SPI NAND 量产会先擦除所有好块再烧录。** SPI NOR 与 SD／eMMC 不另做全设备擦除。
各板按顺序处理；失败不重试，后续开发板仍继续。

## Console 与记录

- **Console**：选择调试 UART 与波特率，按 **Open**；默认为 115200、8N1。更改串口或波特率前先按 **Close**。隐藏窗口仍保持连接，关闭窗口才释放串口。
- **USB Trace**：显示窗口开始记录 USB 传输，隐藏即停止。`<H->D>` 为电脑到开发板，`<D->H>` 为开发板到电脑。记录可能包含镜像内容，分享前请先检查。
- **Op. log**：查看命令、进度与错误，再按同一按钮隐藏。文本可选中与复制。