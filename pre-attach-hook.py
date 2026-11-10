"""Reset the target before NuWriter discovers and opens its USB interface."""

import subprocess
import sys
import time
from pathlib import Path


def main():
    reset_script = Path(__file__).resolve().with_name("ch341_reset_uart.py")
    result = subprocess.run(
        [sys.executable, str(reset_script), "--duration", "0.8"], check=False,
    )
    if result.returncode != 0:
        return result.returncode
    time.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())