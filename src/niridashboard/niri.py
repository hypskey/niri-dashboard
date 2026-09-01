import json
import os
import socket
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


def run_niri_ipc(request):
    socket_path = os.environ["NIRI_SOCKET"]

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(socket_path)
        connection.sendall(
            (json.dumps(request) + "\n").encode("utf-8")
        )

        with connection.makefile("r", encoding="utf-8") as response_file:
            response = json.loads(response_file.readline())

    if "Err" in response:
        raise RuntimeError(response["Err"])

    return response["Ok"]


def move_window_to_workspace(window_id, workspace_id):
    return run_niri_ipc(
        {
            "Action": {
                "MoveWindowToWorkspace": {
                    "window_id": window_id,
                    "reference": {"Id": workspace_id},
                    "focus": False,
                }
            }
        }
    )
