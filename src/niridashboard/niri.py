import json
import subprocess


def get_windows():
    result = subprocess.run(
        ["niri", "msg", "--json", "windows"],
        capture_output=True,
        text=True,
        check=True,
    )

    return json.loads(result.stdout)
