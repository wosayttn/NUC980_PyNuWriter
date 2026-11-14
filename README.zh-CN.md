# NUC980 PyNuWriter

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

NUC980 USB 烧录与 RAM 下载工具。图形界面操作请参阅 [GUI 手册](gui/README.zh-CN.md)。

## 下载独立执行版本

打开[下载页面](https://github.com/wosayttn/NUC980_PyNuWriter/actions)，选择已完成的项目，再从 **Artifacts** 下载 CLI 或 GUI 软件包（需登录 GitHub）。
选择 `nuwriter-cli-<platform>` 或 `nuwriter-gui-<platform>`：

| 系统 | Platform |
| --- | --- |
| Windows x64 | `windows-x64` |
| Linux x64 | `linux-x64` |
| macOS Intel | `macos-x64` |
| macOS Apple Silicon | `macos-arm64` |

解压两层压缩包，保留完整目录，包括 `_internal` 和 `backend`。
macOS 的 `nuwriter-gui.app` 与 `backend` 须放在同一目录。独立版不需安装 Python。
Windows 需安装 [NUC980 WinUSB 驱动程序](driver/README.zh-CN.md)；Linux／macOS 需安装下述 libusb。

GUI 请打开 `nuwriter-gui.exe`、`nuwriter-gui` 或 `nuwriter-gui.app`。
CLI 请将以下示例的 `python nuwriter.py` 改为 Windows 的 `.\nuwriter.exe`，或 Linux／macOS 的 `./nuwriter`。
Linux 软件包面向 Ubuntu 22.04，macOS 软件包面向 macOS 15；旧版系统尚未验证。
软件包未经开发者签名或公证，打开前请确认来源与 SHA-256。

## 从源码安装

在[源代码页面](https://github.com/wosayttn/NUC980_PyNuWriter)选择 **Code > Download ZIP**，下载后解压。
以下命令均在包含 `nuwriter.py` 的目录执行，建议使用 Python 3.14。

### Windows

安装 64 位 [Python](https://www.python.org/downloads/windows/) 和 [NUC980 WinUSB 驱动程序](driver/README.zh-CN.md)。
WinUSB 须安装在开发板的 USB Device 接口，勿选调试 UART 或复位适配器。
使用 CH341 时才需安装其驱动程序。在 PowerShell 执行：

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

### Linux

Debian／Ubuntu 软件包，包含 GUI 所需的库：

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y python3 python3-venv python3-pip libusb-1.0-0 libegl1 libgl1 libxkbcommon0 libxcb-cursor0 libdbus-1-3 fonts-noto-core
```

本地桌面 USB 权限：创建 `/etc/udev/rules.d/70-nuvoton-nuwriter.rules`，内容如下：

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5963", TAG+="uaccess"
```

```bash
sudo udevadm control --reload-rules
```

重新连接开发板。远程／无桌面环境需另行设置 USB 组权限。
串口访问可能还需加入 `dialout` 组。

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

### macOS

安装 [Homebrew](https://brew.sh/)，再安装相同架构的 Python 和 libusb：

```bash
brew install python@3.14 libusb
```

```bash
"$(brew --prefix python@3.14)/bin/python3.14" -m venv .venv
```

```bash
source .venv/bin/activate
```

### Python 软件包

各系统激活虚拟环境后，安装 CLI 依赖包：

```bash
python -m pip install -r requirements.txt
```

GUI 另需安装软件包，再启动程序：

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

## 连接开发板

将开发板设为 USB Boot 模式，连接其 USB Device 接口与电脑。
示例使用 NUC980DK71YC；请选择 `sys_cfg` 中符合开发板的 DDR 配置。

```bash
python nuwriter.py --list
```

```bash
python nuwriter.py -a NUC980DK71YC.ini
```

开发板复位或重新上电后须再次初始化。**初始化可能通过 CH341 复位开发板。** 未使用该适配器时，请手动复位到 USB Boot 模式。
多板连接时，可添加 `--device BUS:PORT`，路径由 `--list` 查询。
下载、烧录、擦除或生成 Pack 前，可在命令末尾添加 `--check`，只检查输入，不访问开发板或写入输出文件。

## 烧录、读取与擦除

示例使用随附的 [sample 文件](sample/README.zh-CN.md)。请先确认开发板的偏移与 Flash 配置。
独立版不含示例；请将源代码 ZIP 中的 `sample` 复制到 CLI 执行文件旁。
烧录主 U-Boot 并验证：

```bash
python nuwriter.py -w spinand 0x100000 sample/u-boot-spinand.bin -o verify
```

读取指定范围或整颗 Flash。输出文件已存在时会覆盖：

```bash
python nuwriter.py -r spinand 0x100000 0x20000 readback.bin
```

```bash
python nuwriter.py -r spinand all backup.bin
```

**全区擦除会删除引导程序、配置与文件系统，请先备份。** NAND／SPI NAND 会保留已标记的坏块。

```bash
python nuwriter.py -e spinand all
```

按需替换 `spinand`。地址与长度单位为 byte，十六进制数值须加 `0x`。

| 媒体 | 写入起点对齐 | 读取起点对齐 | 擦除单位 |
| --- | --- | --- | --- |
| `nand`, `spinand` | Flash 块 | Flash 块 | Flash 块 |
| `spinor` | 4 KiB | 64 KiB | 64 KiB |
| `sd`, `emmc` | 512 bytes | 512 bytes | 不支持 |

SPI NOR 全区读取须添加 `--flash-size`，指定容量（bytes）。
读取与验证不涵盖 OOB 或每个物理坏块。
替换 UBI 镜像前，须擦除旧 rootfs 区域，包括超出新镜像长度的尾部。

## 下载到 RAM

下载并执行主 U-Boot；仅下载时移除 `-o execute`：

```bash
python nuwriter.py -w ddr 0x00e00000 sample/u-boot-spinand.bin -o execute
```

Linux 示例，rootfs 须已安装在 SPI NAND：

```bash
python nuwriter.py -w ddr 0x8000 sample/zImage -o execute --dtb sample/nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M"
```

内核、DTB 与 rootfs 须互相匹配。此方式应执行原始 `zImage`，不可直接执行带 U-Boot 头部的 `uImage`。
下载到 RAM 不会烧录 Flash，但开发板启动的软件可能写入 Flash。

## 生成与烧录 Pack

示例配置使用相对路径。使用独立版 CLI 时，还须将源代码 ZIP 的 `sys_cfg` 复制到执行文件旁。
以下 `python ../nuwriter.py` 请改为 Windows 的 `..\nuwriter.exe`，或 Linux／macOS 的 `../nuwriter`，并在 `sample` 目录执行：

```bash
cd sample
```

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_spinand.json
```

SD1 请改用 `config_sd1.json`，CLI 媒体名称为 `sd`。
生成 Pack 会覆盖配置中指定的输出文件。完成后返回工具目录：

```bash
cd ..
```

初始化后烧录并验证 Pack：

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

```bash
python nuwriter.py -w sd sample/nuwriter-pack-sd.bin --ddr NUC980DK71YC.ini -o verify
```

单板 Pack 烧录不会自动执行全区擦除。
Loader 须排第一，Flash 起点为 `0x0`、SD／eMMC 为 `0x400`；SPI NOR Pack 验证要求各镜像起点对齐 64 KiB。
Pack 验证不比较 Loader 头部／DDR 数据、SD 分区配置、OOB 或未使用区域。

## 量产

所有开发板设为 USB Boot 模式并连接后，初始化及烧录：

```bash
python nuwriter.py -m -a NUC980DK71YC.ini
```

```bash
python nuwriter.py -m -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

**NAND／SPI NAND 会先擦除所有好块再烧录。** SPI NOR 与 SD／eMMC 不另做全设备擦除。
各板按顺序处理，失败不自动重试，后续开发板仍继续；任一板失败会返回非零 exit status。
省略 `-o verify` 也会禁用自动全区擦除步骤。

## 故障排查

- 初始化失败：确认 DDR 配置、USB Boot 模式、USB Device 接口与驱动程序。
- 超时后请等待操作停止，检查或复位开发板，再重新连接。
- 添加 `--trace-usb` 可记录 USB 诊断，记录可能包含镜像内容。
- `--timeout` 设置 USB／重连等待时间，`--operation-timeout` 设置操作等待时间，单位均为毫秒。
- macOS 找不到 libusb 时，启动前先设置路径：

```bash
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix libusb)/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/usr/lib}"
```

## 许可

项目自有程序：[Apache-2.0](LICENSE)。第三方许可与替换权利：[许可声明](licenses/README.md)。
再次分发独立版时，请保留 `licenses/` 和 `sources/`。