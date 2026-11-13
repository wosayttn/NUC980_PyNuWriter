# NUC980 PyNuWriter

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

跨平台的 NUC980 命令行工具与桌面 GUI，支持下载到 RAM、烧录 NAND／SPI Flash，
以及烧录 SD／eMMC。交互操作请参阅[桌面 GUI 指南](gui/README.zh-CN.md)，
命令行操作可按照以下示例进行。

## 下载独立执行版本

独立封装的 CLI 与 GUI 不需要另外安装 Python。

请选择符合所用操作系统与架构的 CLI 或 GUI 软件包。

| 平台 | CLI artifact | GUI artifact |
| --- | --- | --- |
| Windows x64 | `nuwriter-cli-windows-x64` | `nuwriter-gui-windows-x64` |
| Linux x64 | `nuwriter-cli-linux-x64` | `nuwriter-gui-linux-x64` |
| macOS Intel | `nuwriter-cli-macos-x64` | `nuwriter-gui-macos-x64` |
| macOS Apple Silicon | `nuwriter-cli-macos-arm64` | `nuwriter-gui-macos-arm64` |

每个 artifact 包含应用程序压缩包与 `.sha256` 校验文件。先解压下载的 artifact，
再解压其中的 `.zip`（Windows）或 `.tar.gz`（Linux／macOS）。
请保留完整应用程序目录，包括 `_internal` 与 `backend`；此版本采用自包含目录，
不是单文件封装。GUI 已包含 CLI backend，不需要另外下载 CLI。

macOS 解压后的 `nuwriter-gui` 目录内包含 `nuwriter-gui.app` 与同级的 `backend`。
请保留两者，移动时须移动整个目录，不要只取出 `.app`。

GUI 请打开 `nuwriter-gui.exe`、`nuwriter-gui` 或 `nuwriter-gui.app`。
使用下方 CLI 示例时，请在解压后的 `nuwriter` 目录，将 `python nuwriter.py`
改为 Windows 的 `.\nuwriter.exe` 或 Linux／macOS 的 `./nuwriter`。
封装包含 DDR／XUSB 资源与第三方许可证文件，但不包含大型示例镜像，
请另外从此 repository 下载示例文件。

Windows 仍需安装 [NUC980 WinUSB 驱动程序](driver/README.zh-CN.md)；安装程序位于
CLI 的 `_internal/driver`（GUI 封装内则位于 `backend/nuwriter` 下）。
Linux 仍需 USB／串口权限与原生库，Debian／Ubuntu 可执行：

```bash
sudo apt-get install -y libusb-1.0-0 libegl1 libgl1 libxkbcommon0 libxcb-cursor0 libdbus-1-3 fonts-noto-core
```

macOS 请安装与执行文件架构相同的 libusb：

```bash
brew install libusb
```

Linux 软件包需要 Ubuntu 22.04 或兼容的 glibc 系统。macOS 软件包面向 macOS 15，
更旧版本尚未验证。软件包没有开发者签名或公证，Windows／macOS 可能显示
安全警告；打开前请确认来源与校验码。

## 从源码安装

命令行工具需要 Python 3.9 以上版本及 libusb-1.0。CI 使用 Python 3.14；
GUI 请使用 PySide6 支持的 Python 版本。以下命令均从此 repository 目录执行。
请保留程序旁的 `sys_cfg`、`xusb`、`driver` 与 `sample` 目录，
并让 CLI 与 GUI 使用相同的虚拟环境。

### Windows

内置 libusb DLL 为 x64 版本，请安装 x86-64 Python。在 PowerShell 执行：

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

```bash
python -m pip install -r requirements.txt
```

按照[驱动程序指南](driver/README.zh-CN.md)安装 NUC980 WinUSB 驱动程序。
请选择开发板的 USB Device 接口，不要选择调试 VCOM 或 CH341 转接器。
NuWriter 在访问 USB 前会将内置 DLL 目录加入当前进程的 PATH，
不会修改永久 PATH。只有使用选配的 CH341 自动复位转接器时，
才需要安装其驱动程序。

### Linux

以下以 Debian／Ubuntu 为例；其他发行版请安装对应软件包：

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

桌面 GUI 常用的 Qt 系统软件包如下：

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libxcb-cursor0 fonts-noto-core
```

请通过设备权限授予 USB 访问权。若使用已登录的本地桌面会话，
可将以下规则放入 `/etc/udev/rules.d/70-nuvoton-nuwriter.rules`：

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5963", TAG+="uaccess"
```

```bash
sudo udevadm control --reload-rules
```

重新插拔开发板。无桌面或远程用户可能需要改用基于用户组的规则。
串口权限需要另外设置；Debian／Ubuntu 常使用 `dialout` 用户组。
不要将 CH341 串口驱动程序替换为 USB 编程驱动程序。

### macOS

通过 [Homebrew](https://brew.sh/) 安装 Python 与 libusb：

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

Python 与 libusb 必须使用相同架构（arm64 或 x86_64）。
Linux／macOS 使用系统 libusb，不使用 Windows DLL 或 WinUSB 安装程序。

## 桌面 GUI

在已激活的虚拟环境中执行：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

[GUI 指南](gui/README.zh-CN.md)包括 Console、USB Trace、Operation Log、
配置保存与 Mass Production 的操作说明。GUI 需要桌面会话。
启动 GUI 不会自动连接、复位或烧录开发板。

## 示例文件

示例使用内置的 [sample 文件](sample/README.zh-CN.md)与 NUC980DK71YC DDR 配置。
使用前请确认开发板、DDR、Flash 几何配置与启动介质；
示例布局并非适用于所有开发板的通用默认值。

| 模板 | Backend 模式 | 根文件系统 |
| --- | --- | --- |
| [SPI NAND](sample/config_spinand.json) | `spinand` | UBI，位于 0x800000 |
| [SD1](sample/config_sd1.json) | `sd` | ext4，位于 0x800000 |

SD1 是开发板的操作流程名称，不是独立的 CLI 模式。
SD1 模板保留 8 MiB 空间，并建立使用存储卡剩余容量的分区。
其分区记录与预先生成的 SD pack 使用的原始 MBR 不同。
在 RAM 中执行 raw kernel 请使用 `zImage`；Flash pack 模板使用带有 U-Boot header 的 `uImage`。
离线检查通过不代表已成功启动。

## 连接

1. 将开发板设置为 USB Boot 模式并上电。
2. 将开发板的 USB Device 端口连接电脑，不要使用 VCOM／调试端口。
3. 列出设备并初始化 DDR／XUSB：

```bash
python nuwriter.py --list
```

```bash
python nuwriter.py -a NUC980DK71YC.ini
```

复位或重新上电后，请再次初始化。以下后续命令使用已运行的 XUSB。
`--ddr` 只提供 DDR 配置，不会执行初始化。

**自动复位：**若存在 `pre-attach-hook.py`，`-a` 会在连接前执行它。
内置 hook 检测到 CH341 时会通过它复位开发板。没有 CH341 转接器时，
会显示提示并跳过自动复位；请先手动复位开发板进入 USB Boot 模式。
若检测到转接器，但打开或控制失败，操作仍会中止。
离线检查与 pack 生成不会复位开发板。独立 reset helper 未找到 CH341 时，
会返回 exit code 3。

## 烧录与读取 Flash

将主 U-Boot 写入字节地址 `0x100000`，并验证数据：

```bash
python nuwriter.py -w spinand 0x100000 sample/u-boot-spinand.bin -o verify
```

读回 `0x20000` bytes 到文件：

```bash
python nuwriter.py -r spinand 0x100000 0x20000 readback.bin
```

上述烧录只安装主 U-Boot，不包括 SPL、environment、kernel 或 rootfs。
读取操作会创建或覆盖输出文件。读取整个设备可使用：

```bash
python nuwriter.py -r spinand all backup.bin
```

SPI NOR 全设备读取还需要用 `--flash-size` 提供字节容量。
普通读取不包括 OOB／坏块标记，不能视为物理芯片每个字节的完整备份。

**Erase All 会删除 Flash 内容，请先备份需要保留的数据。**
NAND／SPI NAND 擦除会跳过已标记的坏块，并保留其标记：

```bash
python nuwriter.py -e spinand all
```

更新 UBI 镜像前，需要清除整个 rootfs 区域中的旧 UBI 块。
烧录较短的镜像不会清除未写入的尾部块。
Erase All 也会删除 boot loader 与可写入的文件系统，请先备份。

请将 `spinand` 替换为所需介质。地址与长度单位均为 bytes，
十六进制值使用 `0x` 前缀。

| 介质 | 写入起始地址对齐 | 读取起始地址对齐 | 擦除 |
| --- | --- | --- | --- |
| `nand`、`spinand` | Flash 块 | Flash 块 | 完整块 |
| `spinor` | 4 KiB | 64 KiB | 64 KiB 单位 |
| `sd`、`emmc` | 512 bytes | 512 bytes | 不支持 |

## 下载到 RAM

将开发板的主 U-Boot 加载到其链接地址并执行：

```bash
python nuwriter.py -w ddr 0x00e00000 sample/u-boot-spinand.bin -o execute
```

省略 `-o execute` 即只下载、不执行。Linux 可同时下载 kernel 与 DTB；
以下示例使用已安装的 SPI NAND rootfs：

```bash
python nuwriter.py -w ddr 0x8000 sample/zImage -o execute --dtb sample/nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M"
```

请使用匹配的 kernel、DTB 与已安装的 rootfs。
sample 的 `uImage` 带有 U-Boot header，不能直接当作 raw kernel 执行；
此 RAM 流程应使用 `zImage`。`--bootargs` 只修改下载到 RAM 的 DTB 副本。
RAM 下载不会烧录 Flash，但启动后的操作系统可能写入 Flash。
下载与烧录进度以 10% 为间隔显示；100% 不代表下载的软件已成功启动。

## 生成与烧录 Pack

使用 [SPI NAND](sample/config_spinand.json) 或 [SD1](sample/config_sd1.json) 模板。
CLI 的镜像相对路径根据当前工作目录解析，因此请从 `sample` 执行这些配置。
GUI 会自动处理此运行目录。

```bash
cd sample
```

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_sd1.json --check
```

离线检查不会复位、访问开发板或写入输出文件。
生成 pack 时省略 `--check`；以下命令会覆盖指定的 sample pack 文件：

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

| 镜像 `type` | 用途 |
| --- | --- |
| `data`、`linux` | 原样保存文件内容 |
| `loader` | Boot loader，需要 DDR 配置与正确入口地址 |
| `env` | U-Boot environment 文本文件 |
| `partition` | SD／eMMC 分区配置 |

SPI loader 还需要 Flash 命令参数；SPI NAND 需要 page 与 spare 大小。
请使用实际芯片的配置，不要套用其他介质的参数。

初始化后，烧录生成的 pack：

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini
```

单板操作如需擦除，请另外执行。加入 `-o verify` 可在烧录后比较 pack 镜像数据：

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

```bash
python nuwriter.py -w sd sample/nuwriter-pack-sd.bin --ddr NUC980DK71YC.ini -o verify
```

单板 Pack 烧录不会自动增加 Erase All。
Pack Verify 比较镜像数据，不包括 loader header／DDR bytes 与 SD 分区指令。
Loader 必须是第一个镜像，位于 offset 0（Flash）或 0x400（SD／eMMC）。
SPI NOR Pack Verify 要求 offset 对齐 64 KiB；不会验证未使用区域或 OOB。

## 量产模式

先手动将每块开发板复位到 USB Boot 模式，再初始化所有已连接的开发板：

```bash
python nuwriter.py -m -a NUC980DK71YC.ini
```

执行完整的逐板顺序流程：

```bash
python nuwriter.py -m -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

**NAND／SPI NAND 会先执行 Erase All，再进行 Burn／Verify。**
这会删除原有 boot、environment 与文件系统数据，并保留已标记坏块。
SPI NOR 与 SD／eMMC 不执行独立的全设备擦除。
每块开发板回报阶段与结果；失败不自动重试，也不阻止后续开发板继续处理。
整批结束后，若有任一开发板失败，进程会返回非零 exit status。
若未加入 `-o verify`，CLI 的 `-m` 烧录仍按顺序逐板执行，但不自动增加 Erase All。
当前并非并行烧录，GUI 会显示每板的单独阶段与结果。

## 离线检查与故障排查

加入 `--check` 可验证输入，不会复位、访问开发板或写入输出文件。
此检查不会确认已连接 Flash 的实际容量或几何配置。

```bash
python nuwriter.py -a NUC980DK71YC.ini --check
```

多板连接时，可使用 `--list` 获取的路径配合 `--device` 选择单个设备。
USB 诊断可加入 `--trace-usb`；记录包括设备路径，也可能包括镜像数据。
GUI 的 USB Trace 窗口只有显示时才会记录。
`--timeout` 与 `--operation-timeout` 的单位为毫秒。
擦除超时时不要继续烧录；请等待开发板停止操作，再重新初始化。

若 macOS 找不到 Homebrew libusb，请先在当前终端设置搜索路径，再启动 CLI／GUI：

```bash
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix libusb)/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/usr/lib}"
```

## 测试

GitHub Actions 会在 push、pull request 与手动执行时，使用 Python 3.14
在 Windows、Ubuntu 与 macOS 执行 backend 及 offscreen GUI 测试。
请将测试与 sample fixture 一并提交。
测试使用模拟设备或真实 sample 镜像的离线检查，不会连接开发板。
执行两套测试前，请先安装 GUI requirements。

```bash
python -m unittest discover -s . -p test_nuwriter.py -v
```

```bash
python -m unittest discover -s gui -p test_gui.py -v
```

Windows batch 集成测试需要同级的 `numaker-iot-nuc980g2` 目录；
独立 checkout 没有此目录时会跳过该组测试。
原生桌面显示与实体开发板操作仍需要手动测试。

## 许可

项目自有的 Python 源代码与文档采用
[Apache License, Version 2.0](LICENSE)。

内置 libusb 采用 LGPL-2.1-or-later，详见[驱动程序指南](driver/README.zh-CN.md)。
第三方软件、WinUSB 安装程序、XUSB 固件与 DDR 配置文件保留各自的原始许可与版权，
不会因本项目而改变其许可。

独立发行包包含第三方声明、GPL／LGPL 正文、对应版本的库源代码归档，
以及可重新构建的应用程序源代码。再次分发时，请保留 `licenses/` 和 `sources/`。
发行包排除 Qt Virtual Keyboard 及其插件；pyte 保留为可替换的 Python 源代码。
详见[再次分发与替换说明（英文）](licenses/README.md)。
分发者仍须对其分发条件进行法务审核。