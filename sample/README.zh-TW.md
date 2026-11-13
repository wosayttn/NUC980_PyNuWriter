# 範例映像與設定

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[主使用指南](../README.zh-TW.md) | [GUI 指南](../gui/README.zh-TW.md) | [驅動程式指南](../driver/README.zh-TW.md)

GUI 整合測試使用這些真實 NUC980 映像搭配 `--check`，不會存取板子或寫入 pack 輸出。
測試非法輸入、子程序失敗與命令組合時，仍使用小型模擬檔案。

| 設定 | 目標 | 根檔案系統 |
| --- | --- | --- |
| [config_spinand.json](config_spinand.json) | SPI NAND | UBI，位於 0x800000 |
| [config_sd1.json](config_sd1.json) | 板子 SD1，backend 模式 sd | ext4，位於 0x800000 |

路徑相對於此目錄。兩個設定均使用 `../sys_cfg/NUC980DK71YC.ini`。
SD1 範本在第一個分割區前保留 8 MiB，分割區使用剩餘容量；
記憶卡容量必須足以存放 ext4 映像。Host 使用 `sd`，沒有獨立的 `sd1` CLI 模式。

來源映像、U-Boot environment 與 offset 依據提供的 SPI NAND／SD pack 建立。
SD1 範本會產生 backend 的分割紀錄，不會直接複製既有 pack 的原始 MBR。
離線驗證不等於實體板開機測試；燒錄前請確認板子、開機模式與媒體。

`zImage` 是 RAM 下載整合測試使用的 raw ARM Linux kernel。
`uImage` 包含 U-Boot header，仍是 Flash pack 範本的 kernel 輸入。
不要直接將 `uImage` 當作 raw kernel 執行。

從 `sample` 目錄執行下列命令；GUI 會自動將 JSON 目錄設為工作目錄：

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_sd1.json --check
```

確定要產生 pack 時才執行下列命令，這些命令會寫入輸出檔案：

```bash
python ../nuwriter.py -p config_spinand.json
```

```bash
python ../nuwriter.py -p config_sd1.json
```

保留預先產生的 SPI NAND／SD pack 作為 pack program 檢查素材。
不保留重複映像別名、未使用的 UBIFS／WIC 映像、build metadata 與未使用設定檔。