import json
import logging
import os
import re
import subprocess
import sys
import time

import discord

VERSION = "0.0.11b"

if os.getuid() != 0:
    print("This script requires root privileges.")
    sys.exit(-1)

abspath = os.path.abspath(__file__)
bot_location = os.path.dirname(abspath)
os.chdir(bot_location)

logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(handler)

# Load settings
with open("settings.json") as f:
    settings = json.load(f)

    token = settings["discord-token"]
    admin_channels = settings["channels"]["admin"]
    admin_roles = settings["roles"]["admin"]
    admin_users = settings["users"]
    prefix = settings["command-prefix"]
    presence_text = settings["playing-line"]
    docker_info_file = settings["docker-info-file"]
    commands = settings["commands"]
    default_cpu = settings["default-cpus"]
    default_ram = settings["default-ram"]

    del settings

client = discord.Client()
dockers = None

waiting_messages = {}


@client.event
async def on_ready():
    print("Connected to Discord as " + client.user.name)
    await client.change_presence(activity=discord.Game(name=presence_text + f" - {prefix}help"))
    print()


@client.event
async def on_message(message):
    global dockers

    if message.author == client.user:
        return

    input_message = message.content.lower().split(" ")

    if message.channel.id in admin_channels and input_message[0][:len(prefix)] == prefix:
        command = input_message[0][len(prefix):]

        if message.author.id not in admin_users:
            user_role_ids = [role.id for role in message.author.roles]
            if len([i for i in admin_roles if i in user_role_ids]) == 0:
                print("Prevented unauthorized access.")
                await message.channel.send("Sorry - you're not allowed to execute commands.")
                return

        print(command)

        if command == "help":
            output = "These are the available commands:\n"
            for x in commands:
                output += f"• `{x}`: {commands[x]}"
                output += "\n"
            output += f"The command prefix is `{prefix}`\n\nBot version: {VERSION}"
            await message.channel.send(output)

        elif command == "reload":
            async with message.channel.typing():
                load_dockers()
            await message.channel.send("Master container list reloaded.")

        elif command == "ls":
            output = "**Available containers**\n\n"
            async with message.channel.typing():
                # iterate over all challenges
                # list containers and statuses
                for challenge in dockers:
                    segment = ""

                    segment += "**" + dockers[challenge]["long-name"] + f"** (" + dockers[challenge]["category"] + \
							   f") - `{challenge}`\n"
                    segment += " " * 4 + "Type: "

                    # I hereby give this section of code the name of "spaghetti".
                    if dockers[challenge]["type"] == "compose":
                        segment += "compose\n"
                        segment += " " * 4 + "Containers:\n"
                        for container in list_compose_containers(dockers[challenge]["directory"]):
                            status, exitcode = get_container_status(container)
                            ports = get_container_ports(container)
                            segment += " " * 8 + f"`{container}`: {status}" + \
                                       (f" with code {exitcode}" if status == "exited" else "")
                            segment += (", ports " + ",".join(ports)) if len(ports) != 0 else ""
                            segment += "\n"

                    elif dockers[challenge]["type"] == "container":
                        segment += "single container\n"
                        status, exitcode = get_container_status(dockers[challenge]["container-name"])
                        ports = get_container_ports(dockers[challenge]["container-name"])
                        segment += " " * 4 + f"Status: {status}" + \
                                   (f" with code {exitcode}" if status == "exited" else "")
                        segment += (", ports " + ",".join(ports)) if len(ports) != 0 else ""
                        segment += "\n"

                    else:
                        await message.channel.send("Unknown type on " + challenge)
                        return

                    segment += "\n"

                    # Compensate for Discord's 2k character limit
                    if len(segment) + len(output) > 2000:
                        await message.channel.send(output)
                        output = segment
                    else:
                        output += segment

            await message.channel.send(output)

        elif command == "restart":
            if len(input_message) < 2: 
                await message.channel.send("Not enough arguments")
                return

            name = input_message[1]

            output = ""

            async with message.channel.typing():
                if name in dockers:

                    # Challenge shorthand name recognised
                    if dockers[name]["type"] == "compose":

                        restart_compose(dockers[name]["directory"])
                        output += f"Compose cluster `{name}` restarted.\n\n"
                        for container in list_compose_containers(dockers[name]["directory"]):
                            status, exitcode = get_container_status(container)
                            output += " " * 4 + f"`{container}`: {status}" + \
                                      (f" with code {exitcode}" if status == "exited" else "") + "\n"

                    elif dockers[name]["type"] == "container":

                        res = restart_container(dockers[name]["container-name"])
                        if not res[0]:
                            await message.channel.send("Failed: " + res[1])
                            return
                        output += "Single container `" + dockers[name]["container-name"] + "` restarted. \n\n"
                        status, exitcode = get_container_status(dockers[name]["container-name"])
                        output += " " * 4 + "`" + dockers[name]["container-name"] + f"`: {status}" + \
                                  (f" with code {exitcode}" if status == "exited" else "") + "\n"
                    else:
                        await message.channel.send("Unknown type on " + name)
                        return
                else:
                    # Challenge shorthand not recognised, assuming unknown container name

                    res = restart_container(name)
                    if not res[0]:
                        output = "Failed: " + res[1]
                    else:
                        output += f"Single container `{name}` restarted.\n\n"
                        status, exitcode = get_container_status(name)
                        output += " " * 4 + f"`{name}`: {status}" + \
                                  (f" with code {exitcode}" if status == "exited" else "") + "\n"

            await message.channel.send(output)

        elif command == "stop":
            if len(input_message) < 2: 
                await message.channel.send("Not enough arguments")
                return

            name = input_message[1]

            output = ""

            async with message.channel.typing():
                if name == "*":
                    m = await message.channel.send("Are you sure you want to stop all containers? React with :white_check_mark: to proceed.")
                    await m.add_reaction("✅")
                    waiting_messages[m.id] = {"type":"stop", "time":time.time()}
                    return

                elif name in dockers:

                    # Challenge shorthand name recognised
                    if dockers[name]["type"] == "compose":

                        stop_compose(dockers[name]["directory"])
                        output += f"Compose cluster `{name}` stopped.\n\n"
                        for container in list_compose_containers(dockers[name]["directory"]):
                            status, exitcode = get_container_status(container)
                            output += " " * 4 + f"`{container}`: {status}" + \
                                      (f" with code {exitcode}" if status == "exited" else "") + "\n"

                    elif dockers[name]["type"] == "container":

                        res = stop_container(dockers[name]["container-name"])
                        if not res[0]:
                            await message.channel.send("Failed: " + res[1])
                            return
                        output += "Single container `" + dockers[name]["container-name"] + "` stopped. \n\n"
                        status, exitcode = get_container_status(dockers[name]["container-name"])
                        output += " " * 4 + "`" + dockers[name]["container-name"] + f"`: {status}" + \
                                  (f" with code {exitcode}" if status == "exited" else "") + "\n"
                    else:
                        await message.channel.send("Unknown type on " + name)
                        return
                else:
                    # Challenge shorthand not recognised, assuming unknown container name

                    res = stop_container(name)
                    if not res[0]:
                        output = "Failed: " + res[1]
                    else:
                        output += f"Single container `{name}` stopped.\n\n"
                        status, exitcode = get_container_status(name)
                        output += " " * 4 + f"`{name}`: {status}" + \
                                  (f" with code {exitcode}" if status == "exited" else "") + "\n"

            await message.channel.send(output)

        elif command == "start":
            if len(input_message) < 2: 
                await message.channel.send("Not enough arguments")
                return

            name = input_message[1]

            output = ""

            async with message.channel.typing():
                if name == "*":
                    m = await message.channel.send("Are you sure you want to start all containers? React with :white_check_mark: to proceed.")
                    await m.add_reaction("✅")
                    waiting_messages[m.id] = {"type":"start", "time":time.time()}
                    return

                elif name in dockers:

                    # Challenge shorthand name recognised
                    if dockers[name]["type"] == "compose":

                        start_compose(dockers[name]["directory"])
                        output += f"Compose cluster `{name}` started.\n\n"
                        for container in list_compose_containers(dockers[name]["directory"]):
                            status, exitcode = get_container_status(container)
                            output += " " * 4 + f"`{container}`: {status}" + \
                                      (f" with code {exitcode}" if status == "exited" else "") + "\n"

                    elif dockers[name]["type"] == "container":

                        res = start_container(dockers[name]["container-name"])
                        if not res[0]:
                            await message.channel.send("Failed: " + res[1])
                            return
                        output += "Single container `" + dockers[name]["container-name"] + "` started. \n\n"
                        status, exitcode = get_container_status(dockers[name]["container-name"])
                        output += " " * 4 + "`" + dockers[name]["container-name"] + f"`: {status}" + \
                                  (f" with code {exitcode}" if status == "exited" else "") + "\n"
                    else:
                        await message.channel.send("Unknown type on " + name)
                        return
                else:
                    # Challenge shorthand not recognised, assuming unknown container name

                    res = start_container(name)
                    if not res[0]:
                        output = "Failed: " + res[1]
                    else:
                        output += f"Single container `{name}` started.\n\n"
                        status, exitcode = get_container_status(name)
                        output += " " * 4 + f"`{name}`: {status}" + \
                                  (f" with code {exitcode}" if status == "exited" else "") + "\n"

            await message.channel.send(output)

        elif command == "init":
            async with message.channel.typing():
                m = await message.channel.send("Are you sure you want to initialise all challenges? Likelihood is that this has always been done and you do not need to do it. This will cause outages and realistically you probably do not need to run it. Unless you're Tom, in which case go ahead. If you're not, you can do this or you can walk away and forget this ever happened. Did I mention you probably don't need to do this?\nReact with :white_check_mark: to proceed.")
                await m.add_reaction("✅")
                waiting_messages[m.id] = {"type":"init", "time":time.time()}
                return

        elif command == "logs":
            name = input_message[1]

            if name in dockers:
                if dockers[name]["type"] == "compose":
                    await message.channel.send("This function only works with containers directly.")
                    return
                else:
                    logs, _ = container_logs(name)
                    if len(logs) > 1930:
                        logs = logs[len(logs)-1930:]
                    logs = escape_ansi(logs)
                    await message.channel.send(f"Logs for `{name}`\n```\n{logs}\n```")

			
        else:
            await message.channel.send("Unknown command")


@client.event
async def on_reaction_add(reaction, user):

    if user == client.user:
        return

    # holy wall of text
    if reaction.message.id in waiting_messages:
        if (time.time() - waiting_messages[reaction.message.id]["time"]) < 30:
            r = waiting_messages.pop(reaction.message.id)
            if r["type"] == "start":
                await reaction.message.channel.send("Starting all challenges")
                for chall in dockers:
                    print("Starting", chall)
                    m = await reaction.message.channel.send(f"Starting `{chall}`...")
                    if dockers[chall]["type"] == "compose":
                        start_compose(dockers[chall]["directory"])
                    elif dockers[chall]["type"] == "container":
                        c = dockers[chall]
                        start_container(c["container-name"])
                    await m.edit(content=f"`{chall}` started.")
                await reaction.message.channel.send(":tada: All containers started.")

            elif r["type"] == "stop":
                await reaction.message.channel.send("Stopping all challenges")
                for chall in dockers:
                    print("Stopping", chall)
                    m = await reaction.message.channel.send(f"Stopping `{chall}`...")
                    if dockers[chall]["type"] == "compose":
                        stop_compose(dockers[chall]["directory"])
                    elif dockers[chall]["type"] == "container":
                        c = dockers[chall]
                        stop_container(c["container-name"])
                    await m.edit(content=f"`{chall}` stopped.")
                await reaction.message.channel.send(":tada: All containers stopped.")

            elif r["type"] == "init":
                await reaction.message.channel.send("Initialising all challenges. This might take a moment or two.")
                for container in get_all_containers():
                    m = await reaction.message.channel.send(f"Removing `{container}`...")
                    remove_container(container)
                    await m.edit(content=f"`{container}` removed.")

                for chall in dockers:
                    m = await reaction.message.channel.send(f"Creating `{chall}`...")
                    if dockers[chall]["type"] == "compose":
                        create_compose(dockers[chall]["directory"])
                    elif dockers[chall]["type"] == "container":
                        c = dockers[chall]
                        if "cpu" in c:
                            cpus = c["cpu"]
                        else:
                            cpus = default_cpu

                        if "ram" in c:
                            ram = c["ram"]
                        else:
                            ram = default_ram

                        create_container(c["container-name"], c["create-args"], c["image"], ram, cpus)
                    await m.edit(content=f"`{chall}` created.")
                await reaction.channel.message.send(":tada: All challenges initialised.")




# Helper functions

def escape_ansi(line):
    ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')
    return ansi_escape.sub('', line)


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


def validate_container_command(output: str, name: str) -> tuple:
    """
    Validates output from one of the *_container functions, eg start_container.
    :param output: output from the command line
    :param name: container name or ID
    :return: success boolean, message
    """
    if "no such container" in output:
        return False, "no such container"
    elif output != name.lower():
        return False, output
    else:
        return True, "ok"


# Miscellaneous functions

def load_dockers():
    """
    Loads Docker container information from the file specified as docker-info-file in the settings JSON
    :return: None
    """
    global dockers
    dockers = json.load(open(docker_info_file))


def list_compose_containers(directory: str) -> list:
    """
    Lists containers that form a compose cluster
    :param directory: The directory of the Docker compose cluster
    :return: list of container names
    """
    os.chdir(directory)
    result, _ = run_command(["sudo", "docker-compose", "ps"])
    result = result.split("\n")[2:]
    os.chdir(bot_location)
    return [line.split(" ")[0] for line in result]


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


def get_container_ports(name: str) -> list:
    """
    Gets ports that are exposed on the container with the specified name
    :param name: container name or ID
    :return: list of ports that are open as strings in the form [host]:[container]
    """
    result, _ = run_command(["sudo", "docker", "inspect", name])
    if "no such container" in result:
        return "no such container"
    try:
        j = json.loads(result)[0]
    except json.decoder.JSONDecodeError:
        return result

    ports = []

    if "NetworkSettings" not in j:
        return []
    else:
        for port in j["NetworkSettings"]["Ports"]:
            if j["NetworkSettings"]["Ports"][port] is not None:
                internal_port = port.split("/")[0]
                host_port = j["NetworkSettings"]["Ports"][port][0]["HostPort"]
                ports.append(f"{host_port}:{internal_port}")

        return ports


def get_all_containers():
    """
    Gets all container IDs that exist (running or stopped)
    :return: list of container IDs
    """
    cmd, _ = run_command(["sudo", "docker", "ps", "-a"])
    cmd = cmd.strip().split("\n")[1:]
    return [line.split(" ")[0] for line in cmd]


def remove_container(name: str):
    """
    Stops and removes specified container
    :param name: container name or ID
    :return: None
    """
    run_command(["sudo", "docker", "stop", name])
    run_command(["sudo", "docker", "rm", name])


def container_logs(name: str) -> tuple:
    """
    Equiv of running sudo docker logs name
    :param name: duh
    :return: text response, if container name was used
    """
    return run_command(["sudo", "docker", "logs", name])


# Create functions

def create_compose(directory: str):
    """
    Creates containers that form a compose cluster
    :param directory: Directory of the Docker compose cluster
    :return: None
    """
    os.chdir(directory)
    run_command(["sudo", "docker-compose", "up", "--no-start"])
    os.chdir(bot_location)


def create_container(name: str, arguments: list, image: str, memory: str, cpus: str):
    """
    Creates container
    :param name: container name to be
    :param arguments: arguments that would be command line arguments
    :param image: image name to make the container with
    :return: None. Will exit entire script on error.
    """
    result, error = run_command(["sudo", "docker", "create", f"--name={name}", *arguments, image])
    if error:
        print(result)
        sys.exit(-1)


# Restart functions

def restart_compose(directory: str):
    """
    Restarts Docker compose cluster
    :param directory: Directory of cluster
    :return: None
    """
    os.chdir(directory)
    run_command(["sudo", "docker-compose", "restart"])
    os.chdir(bot_location)


def restart_container(name: str) -> tuple:
    """
    Restarts container
    :param name: container name or ID
    :return: success boolean, message
    """
    result, _ = run_command(["sudo", "docker", "restart", name])
    result = result.lower()
    return validate_container_command(result, name)


# Stop functions

def stop_compose(directory: str):
    """
    Stops Docker compose cluster
    :param directory: directory of cluster
    :return: None
    """
    os.chdir(directory)
    run_command(["sudo", "docker-compose", "stop"])
    os.chdir(bot_location)


def stop_container(name: str) -> tuple:
    """
    Stops container
    :param name: container name or ID
    :return: success boolean, message
    """
    result, _ = run_command(["sudo", "docker", "stop", name])
    result = result.lower()
    return validate_container_command(result, name)


# Start functions

def start_compose(directory: str):
    """
    Starts Docker compose cluster
    :param directory: directory of cluster
    :return: None
    """
    os.chdir(directory)
    run_command(["sudo", "docker-compose", "up", "-d"])
    os.chdir(bot_location)


def start_container(name: str) -> tuple:
    """
    Starts Docker container
    :param name: container name or ID
    :return: success boolean, message
    """
    result, _ = run_command(["sudo", "docker", "start", name])
    result = result.lower()
    return validate_container_command(result, name)


load_dockers()
print("Container information loaded")

if len(sys.argv) >= 2:
    if "init" in sys.argv:
        print("Setting up containers")
        containers = get_all_containers()
        for container in get_all_containers():
            print("Removing", container)
            remove_container(container)

        for chall in dockers:
            print("Creating", chall)
            if dockers[chall]["type"] == "compose":
                create_compose(dockers[chall]["directory"])
            elif dockers[chall]["type"] == "container":
                c = dockers[chall]
                if "cpu" in c:
                    cpus = c["cpu"]
                else:
                    cpus = default_cpu

                if "ram" in c:
                    ram = c["ram"]
                else:
                    ram = default_ram

                create_container(c["container-name"], c["create-args"], c["image"], ram, cpus)

    if "bot" not in sys.argv:
        sys.exit()
else:
    print("""Provide one (or more) of the following command line arguments:
    init - remove all preexisting Docker containers and recreate from the Docker container file.
    bot - start the Discord bot""")
    sys.exit()

client.run(token)
