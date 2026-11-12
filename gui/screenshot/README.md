# GUI screenshots

Windows captures of all seven media pages and the main popup states.
Images contain window client areas; native title bars are not included.
File pickers use Qt dialogs, so they may differ from the operating system's native dialogs.

Console, progress, and diagnostic output are sample data. No USB/UART device was
opened, no board operation was run, and all confirmations and file dialogs were cancelled.

## Media pages

| Image | State |
| --- | --- |
| [01_sdram.png](01_sdram.png) | SDRAM download |
| [01b_sdram_dtb.png](01b_sdram_dtb.png) | SDRAM with DTB, bootargs, and execution selected |
| [02_spi_nor.png](02_spi_nor.png) | SPI NOR data image |
| [03_nand.png](03_nand.png) | NAND data image |
| [04_sd_emmc.png](04_sd_emmc.png) | SD/eMMC loader image |
| [05_spinand.png](05_spinand.png) | SPI NAND data image |
| [05b_spinand_pack.png](05b_spinand_pack.png) | SPI NAND pack image |
| [06_pack.png](06_pack.png) | Pack configuration with six image entries |
| [07_mass_production.png](07_mass_production.png) | Mass Production pack selection |

## Console and log

| Image | State |
| --- | --- |
| [08_console_open.png](08_console_open.png) | Port selected, disconnected, Open button |
| [09_console_connected.png](09_console_connected.png) | Mock COM30 connected, ANSI colors, Close button |
| [10_console_disconnected.png](10_console_disconnected.png) | Simulated unplug, Open button restored |
| [11_operation_log.png](11_operation_log.png) | Commands, progress, results, and errors; 320 px high |
| [38_console_context_menu.png](38_console_context_menu.png) | Terminal Copy/Paste menu while disconnected |

## Operation dialogs

| Image | State |
| --- | --- |
| [12_read_range.png](12_read_range.png) | Read a flash range |
| [13_read_all.png](13_read_all.png) | Read All |
| [14_read_spinor_all.png](14_read_spinor_all.png) | SPI NOR Read All with flash size |
| [15_erase_all.png](15_erase_all.png) | Erase All |
| [16_erase_range.png](16_erase_range.png) | Erase a flash range |
| [17_format_sd_emmc.png](17_format_sd_emmc.png) | SD/eMMC partition settings |
| [18_pack_add_data.png](18_pack_add_data.png) | Add a Pack data image |
| [19_pack_edit_loader.png](19_pack_edit_loader.png) | Edit a loader with additional JSON parameters |
| [20_pack_partition.png](20_pack_partition.png) | Pack partition record |

## Confirmations and errors

| Image | State |
| --- | --- |
| [21_confirm_reconnect.png](21_confirm_reconnect.png) | Re-Connect/reset warning |
| [22_confirm_program.png](22_confirm_program.png) | Program warning |
| [23_confirm_erase.png](23_confirm_erase.png) | Erase warning |
| [24_confirm_execute.png](24_confirm_execute.png) | SDRAM execution warning |
| [25_confirm_format.png](25_confirm_format.png) | Format, partition-table replacement, and reset warning |
| [26_confirm_mass_production.png](26_confirm_mass_production.png) | Mass Production warning |
| [27_confirm_overwrite.png](27_confirm_overwrite.png) | Pack output replacement warning |
| [28_confirm_stop.png](28_confirm_stop.png) | Stop-operation warning |
| [29_error_message.png](29_error_message.png) | Missing-file error |
| [30_invalid_pack_image.png](30_invalid_pack_image.png) | Invalid Pack image error |
| [31_confirm_console_paste.png](31_confirm_console_paste.png) | Multiline terminal paste warning |

## File dialogs

| Image | State |
| --- | --- |
| [32_open_image_file.png](32_open_image_file.png) | Choose image files |
| [33_open_ddr_file.png](33_open_ddr_file.png) | Choose a DDR INI from sys_cfg |
| [34_open_pack_config.png](34_open_pack_config.png) | Open Pack JSON |
| [35_save_readback.png](35_save_readback.png) | Choose readback destination |
| [36_save_pack_config.png](36_save_pack_config.png) | Save Pack JSON |
| [37_save_pack_output.png](37_save_pack_output.png) | Choose Pack binary destination |