# NuWriter 桌面 GUI

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主使用指南](../README.zh-CN.md) | [示例指南](../sample/README.zh-CN.md) | [驱动程序指南](../driver/README.zh-CN.md)

现有 NuWriter backend 的跨平台 Qt 前端。主要布局包括 Choose type、DDR Init、
Re-Connect、镜像列表、Parameters 与操作按钮。Backend 作为独立进程执行。

## 安装与启动

独立版本请按照[下载指南](../README.zh-CN.md#下载独立执行版本)，
选择 `nuwriter-gui-<platform>`，解压完整封装后打开 `nuwriter-gui.exe`（Windows）、
`nuwriter-gui`（Linux）或 `nuwriter-gui.app`（macOS）。封装已包含 Python 与 CLI
backend，请保留 `backend` 目录及内置资源；仍需安装原生 USB 驱动程序／库。

如需从源码运行：

从 `NUC980_PyNuWriter` 目录，使用你的 Python 环境执行：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

Linux／macOS 如有需要可使用 `python3`。PySide6 需要桌面会话；Linux 也需要
系统 libusb 与 Qt 平台库。Debian／Ubuntu 若提示缺少 xcb cursor 库，
请安装 `libxcb-cursor0`。Windows 需要 NUC980 WinUSB 驱动程序；内置 DLL 需要 64-bit Python。

源码版本的 GUI 与 backend 使用相同的 Python interpreter；独立版本使用内置的
CLI 执行文件。启动 GUI 不会打开串口、扫描 USB、
复位开发板或写入 Flash。主窗口从屏幕可用区域左上角开始显示，没有 Help 菜单。
更新后请重新安装 GUI requirements，包括 ANSI 终端处理所需的 `pyte`。

## 串口 Console

**Console**、**USB Trace** 与 **Op. log** 位于 USB Device 行的 **Refresh** 右侧，
右对齐，backend 操作期间仍可使用。点击 **Console** 显示或隐藏 Console 窗口。
Port 列表、baud rate、Refresh 与 **Open** 都位于该窗口内。
请选择开发板的调试 UART／VCOM，而非 CH341 复位转接器，再按 **Open** 连接。
显示窗口不会自动打开串口；插拔转接器后请刷新列表。

首次没有几何记录时，Console 与主窗口同大小，显示在右侧并对齐上沿。
之后隐藏或关闭会保留位置与大小；重开时恢复，不再跟随主窗口移动或缩放。
几何信息也会保存到配置，供下次 APP 执行恢复。原屏幕不存在时 Qt 可能调整位置；
Wayland 也可能覆盖窗口位置。终端不显示水平／垂直滚动条，可用鼠标滚轮查看历史；
新输出会返回最新文本。

黑底终端接收 UART 输出，并直接接受键盘输入。默认为 115200 baud、8 data bits、
无 parity、1 stop bit、无 flow control。Enter 发送 CR，方向键发送终端控制序列，
Ctrl+C 在未选中文本时发送 interrupt；若已选中文本则复制。
输入没有本地 echo，显示内容由开发板决定。粘贴多行文本需要确认。

只使用一个 Console 窗口／连接。用 **Console** 隐藏窗口会保留连接与输出，重开保留历史。
连接按钮未连接时为 **Open**，成功连接后为 **Close**。更换 port／baud 前请先按 **Close**。
打开失败、关闭或设备移除后会回到 **Open**。
关闭 Console、在终端输入区域外按 Esc，或关闭主窗口，会释放串口。
Backend 操作期间仍可使用 Console。

ANSI 前景／背景支持标准与亮色、256 色、RGB，以及粗体、斜体、下划线、删除线、
反色与颜色重置；`pyte` 也处理光标移动与清除。
Console 没有 Save／Clear 按钮，但可选中与复制文本。
打开前会请求 DTR／RTS 为非活动状态；部分转接器／驱动仍可能产生脉冲，请确认接线。

## USB Trace

**Console** 旁的 **USB Trace** 按钮可显示或隐藏 Trace 窗口。
显示时启用记录；隐藏或关闭时停用记录、backend trace 格式化及 GUI trace 处理。
操作执行中也会生效，不重启 backend 或中断 USB 传输。

Trace 显示在主窗口右侧、上沿对齐，跟随主窗口移动／缩放，但保留自身大小。
它留在主窗口所在屏幕；空间不足时可能重叠。Wayland compositor 可能覆盖请求的位置。

Trace 只进入此窗口；命令、进度与错误保留在 Operation Log。
Trace 使用黑底彩色等宽文本。`<H->D>` 表示 host 到 device，`<D->H>` 表示 device 到 host。
每笔事务用前面的 USB bus／port 路径标识设备，例如
`[2:4.2.2] <H->D> CONTROL OUT request=0xb0 value=0x0080 index=0 length=0`。
Bulk endpoint 地址仍位于 `endpoint=`；没有设备路径信息的记录不加该前缀。
不显示 `data=`。数据从下一行开始，每行 16 bytes，首字对齐事务名称 `BULK`／`CONTROL`。
缩进根据设备路径与方向前缀调整，沿用事务颜色；截断时 `...` 独立显示在同缩进的一行。

| 事务 | 前缀 | 颜色 |
| --- | --- | --- |
| CONTROL OUT | `<H->D>` | 蓝 |
| CONTROL IN | `<D->H>` | 青 |
| BULK OUT | `<H->D>` | 黄 |
| BULK IN | `<D->H>` | 绿 |

隐藏／关闭保留现有内容，但不新增记录。只使用一个 Trace 窗口，操作期间按钮仍可用。
保留最新 10,000 行，新输出滚动到最新项。文本可选中复制；记录可能包含镜像或读回数据，
分享前请先检查。

## 烧录 Flash

1. 准备 USB Boot 模式并连接 USB Device 端口。
2. 选择开发板的 DDR Init，用 Refresh 列出目标；单板也可保持 Auto。
3. 按 Re-Connect 初始化 DDR／XUSB，会执行 pre-attach reset hook。
4. 选择 SPI NAND、SPI NOR、NAND 或 SD／eMMC，选择文件并设置 Data、Environment、Loader 或 Pack。
5. 设置镜像起始 offset／execute address，再按 Program。

DDR Init 只列出项目相对 `sys_cfg` 目录中的 INI，不能浏览外部 DDR 文件。
路径根据项目位置解析，不依赖当前工作目录。地址与 read／erase 长度单位都是 bytes，
十六进制使用 `0x`。Loader 需要正确 DDR 与链接入口地址；Flash offset 为 0，
SD／eMMC 为 `0x400`。每个操作先做离线检查，失败不会开始实际操作。
Save JSON 直接写入配置文件。

## 操作

| 操作 | 行为 |
| --- | --- |
| Program | 只烧录选中行，目标位置原有数据可能被覆盖 |
| Program + Verify | 烧录一个镜像，再由 backend 读回验证 |
| Verify | 只读回 Data 镜像并比较，不烧录 |
| Read | 保存指定范围或整个设备到文件 |
| Erase | 确认后擦除所有好块或对齐范围 |
| Format | 仅 SD／eMMC，替换分区／format 数据并重新初始化 DDR／XUSB |

独立 Verify 仅支持 Data；Loader／Environment 使用 Program + Verify，Pack 也支持此选项。
Read／Verify 遵守 backend 的读取对齐要求，SPI NOR 包括 64 KiB。
SD／eMMC Format 使用 MiB，最后一个分区使用剩余容量。
Format／Erase 会删除数据，中断后不能撤销已写入或擦除的数据；重新连接前请检查或复位开发板。
操作完成后，可用标题栏关闭按钮退出。

## SDRAM

选择 SDRAM、镜像与地址，再选择 Download only 或 Download and run。
启用 DTB file 可提供 DTB／地址；bootargs 只修改下载的 DTB 副本。
RAM 执行后的软件可能访问 Flash，传输完成不代表成功启动。

## Pack

Pack 可打开／编辑 JSON。Add、Modify、Delete 修改镜像表格，Save JSON 保存配置。
`ddr_ini`、`page_size` 与 SPI 命令等 loader 参数放在 Additional JSON parameters；
SD／eMMC 分区记录使用 backend 相同字段。

Output 不连接开发板，只生成 pack；使用编辑后配置的临时快照，不会修改已打开的 JSON。
镜像／DDR 相对路径根据配置目录解析；Save JSON 保留该目录，避免相对路径改变含义。
操作完成或取消后删除快照。

Mass Production 顺序处理目标，每板先检查，再 Erase、Burn、Pack Verify。
NAND／SPI NAND 先 Erase All，保留坏块标记，但删除原有 boot、environment 与文件系统。
SPI NOR／SD／eMMC 跳过独立的全设备擦除。Re-Connect 仍顺序初始化所有开发板。
结果表格根据 USB 设备路径显示 Erase／Burn／Verify／最终结果。
一板失败不重试，后续开发板继续；任何失败都会使整批失败。
非法 Pack／DDR 配置在烧录前拒绝。当前没有并行烧录或自动 reset／retry；开始 MP 前请备份。

Pack Verify 使用固件 action 7 读回镜像；比较不包括 loader header／DDR 与 SD 分区指令。
Loader 必须是第一个镜像，offset 为 0（Flash）或 0x400（SD／eMMC）；
SPI NOR offset 必须对齐 64 KiB。Verify 只覆盖 pack 镜像数据，不是所有物理／OOB 或未使用区域。

## 配置保存与输入验证

关闭 APP 会在 Qt 用户配置目录（`QStandardPaths.AppConfigLocation`）保存 `settings.json`。
Windows 通常为 `%LOCALAPPDATA%/NUC980 PyNuWriter`；Linux 通常为
`~/.config/NUC980 PyNuWriter`，或 `XDG_CONFIG_HOME` 指定的目录。

JSON 保存 media／DDR／USB target、镜像列表与选中行、各页字段／选项、Pack 草稿／路径、
弹窗默认值、Console port／baud 及窗口大小。DDR 仍限于内置 `sys_cfg`，旧平台配置会迁移 DDR 选项。
不恢复 log、连接、执行中操作与弹窗显示状态；启动不会连接或烧录。

采用原子写入。非法 JSON 使用默认值，写入新文件前备份为 `settings.json.<timestamp>.invalid`。
单个非法值会忽略；保存失败会提示并保持 APP 打开，避免无提示地丢失配置。
地址／长度需要 `0x` 加 1 到 8 位十六进制数字（`0x0` 至 `0xffffffff`）。
输入时拒绝非法字符，未完成或超范围的值不能开始操作；read／erase 长度必须非零。
分区数值控件限制范围，路径与 bootargs 拒绝控制字符，源／输出路径使用前检查。
Pack 额外参数必须是 JSON object；backend preflight 仍检查镜像格式、对齐与设备相关约束。

## Log 与测试

每次 APP 执行第一次打开 Operation Log，才获取 host OS／kernel、CPU 架构／核心数、
RAM 总量／可用量、Python interpreter、Qt platform、屏幕大小／DPI scale 与配置文件位置。
也通过 package metadata 列出 PySide6、pyte、pyserial、psutil、PyUSB、pyfdt 版本与加载状态，
不会为了查询版本而加载延后使用的 backend 模块。缺少的硬件信息标为 unavailable。
主窗口启动时不查询这些信息，隐藏／重开 log 也不重查；不扫描 USB 或打开串口。
记录保留在 log，不保存到配置。

**Op. log** 切换非 modal 窗口，显示时按钮保持勾选，只使用一个 log 窗口。
隐藏时仍累积普通输出，重开保留。窗口位于主窗口下方，外框同宽，高度固定 320，
跟随主窗口移动／缩放，退出主窗口也会隐藏 log。
标题栏为 **NuWriter - Operation Log**，可以拖动；没有最小化、最大化、关闭、Save 或 Clear 按钮。
Esc／Alt+F4 不会关闭，请用 **Op. log** 隐藏；Console 控件不变。

命令为蓝色，普通 backend 结果为绿色；包含 `Error`（不区分大小写）的结果行为红色。
文本可选中／复制，新输出自动滚动到最新。主窗口为 800x560，Flash 控件保持左右并排。
同时只能执行一个操作。

```bash
python -m unittest discover -s gui -p test_gui.py -v
```

测试使用模拟进程及真实 backend 的离线检查，不操作硬件。
真实镜像集成案例使用 [sample](../sample/README.zh-CN.md) 中的文件与 SPI NAND／SD1 模板；
请随测试一并提交素材，离线检查不写入 pack 输出。
Windows 显示／离线流程已检查；Linux／macOS 与实体开发板 GUI 操作仍需平台测试。
GUI 不支持 raw／OOB 编程或自定义设备几何配置，不启动 Windows executable，也不修改 backend 源代码。