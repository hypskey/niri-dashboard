import json
import subprocess


def run_niri_json(command):
    result = subprocess.run(
        ["niri", "msg", "--json", command],
        capture_output=True,
        text=True,
        check=True,
    )

    return json.loads(result.stdout)


def get_windows():
    return run_niri_json("windows")


def get_workspaces():
    return run_niri_json("workspaces")


def get_outputs():
    return run_niri_json("outputs")


def focus_window(window_id):
    subprocess.run(
        [
            "niri",
            "msg",
            "action",
            "focus-window",
            "--id",
            str(window_id),
        ],
        check=True,
    )
