# 示例镜像与配置

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主使用指南](../README.zh-CN.md) | [GUI 指南](../gui/README.zh-CN.md) | [驱动程序指南](../driver/README.zh-CN.md)

GUI 集成测试使用这些真实 NUC980 镜像配合 `--check`，不会访问开发板或写入 pack 输出。
测试非法输入、子进程失败与命令组合时，仍使用小型模拟文件。

| 配置 | 目标 | 根文件系统 |
| --- | --- | --- |
| [config_spinand.json](config_spinand.json) | SPI NAND | UBI，位于 0x800000 |
| [config_sd1.json](config_sd1.json) | 开发板 SD1，backend 模式 sd | ext4，位于 0x800000 |

路径相对于此目录。两个配置均使用 `../sys_cfg/NUC980DK71YC.ini`。
SD1 模板在第一个分区前保留 8 MiB，分区使用剩余容量；
存储卡容量必须足以存放 ext4 镜像。Host 使用 `sd`，没有独立的 `sd1` CLI 模式。

源镜像、U-Boot environment 与 offset 根据提供的 SPI NAND／SD pack 建立。
SD1 模板会生成 backend 的分区记录，不会直接复制已有 pack 的原始 MBR。
离线验证不等于实体开发板启动测试；烧录前请确认开发板、启动模式与介质。

`zImage` 是 RAM 下载集成测试使用的 raw ARM Linux kernel。
`uImage` 包含 U-Boot header，仍是 Flash pack 模板的 kernel 输入。
不要直接将 `uImage` 当作 raw kernel 执行。

从 `sample` 目录执行以下命令；GUI 会自动将 JSON 目录设为工作目录：

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_sd1.json --check
```

确定要生成 pack 时才执行以下命令，这些命令会写入输出文件：

```bash
python ../nuwriter.py -p config_spinand.json
```

```bash
python ../nuwriter.py -p config_sd1.json
```

保留预先生成的 SPI NAND／SD pack 作为 pack program 检查素材。
不保留重复镜像别名、未使用的 UBIFS／WIC 镜像、build metadata 与未使用配置文件。