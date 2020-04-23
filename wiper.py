import os
import subprocess
import json

def run_command(command: list) -> tuple:
    """
    Runs a command
    :param command: elements of command to be run
    :return: text output of command, boolean indicating if stderr was used
    """
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.stdout == b"":
        result = result.stderr
        error = True
    else:
        result = result.stdout
        error = False
    return result.decode().strip("\n"), error

def get_container_status(name: str) -> tuple:
    """
    Gets the status of the specified container (eg created, running, stopped, etc)
    :param name: container name od ID
    :return: status as string, exit code as int (zero if not exited)
    """
    result, _ = run_command(["sudo", "docker", "inspect", name])
    if "no such container" in result:
        return "no such container", 0
    try:
        j = json.loads(result)[0]
    except json.decoder.JSONDecodeError:
        return result, 0

    if "State" not in j:
        return "created", 0
    else:
        return j["State"]["Status"], j["State"]["ExitCode"]

if get_container_status("selfhosteverything_app_1")[0] == "running":
  os.system("sudo docker exec selfhosteverything_app_1 rm /root/.config/mantle/access.db")
  os.system("sudo docker restart selfhosteverything_app_1")