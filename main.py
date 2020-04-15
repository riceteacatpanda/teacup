import discord
import os
import json
import logging
import subprocess
import sys
import tqdm

VERSION = "0.0.1a"

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

	del settings

client = discord.Client()


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

					segment += "**" + dockers[challenge]["long-name"] + f"** - `{challenge}`\n"
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

		elif len(input_message) < 2:
			await message.channel.send("Not enough arguments.")

		elif command == "restart":
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
			name = input_message[1]

			output = ""

			async with message.channel.typing():
				if name in dockers:

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
			name = input_message[1]

			output = ""

			async with message.channel.typing():
				if name in dockers:

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


# Helper functions

def run_command(command):
	result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	if result.stdout == b"":
		result = result.stderr
		error = True
	else:
		result = result.stdout
		error = False
	return result.decode().strip("\n"), error


def validate_container_command(output, name):
	if "no such container" in output:
		return False, "no such container"
	elif output != name.lower():
		return False, output
	else:
		return True, "ok"


# Miscellaneous functions

def load_dockers():
	"""
	Returns Docker container information from the file specified as docker-info-file in the settings JSON
	"""
	global dockers
	dockers = json.load(open(docker_info_file))


def list_compose_containers(directory):
	os.chdir(directory)
	result, _ = run_command(["sudo", "docker-compose", "ps"])
	result = result.split("\n")[2:]
	os.chdir(bot_location)
	return [line.split(" ")[0] for line in result]


def get_container_status(name):
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


def get_container_ports(name):
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
	cmd, _ = run_command(["sudo", "docker", "ps", "-a"])
	cmd = cmd.strip().split("\n")[1:]
	cmd = [line.split(" ")[0] for line in cmd]
	return cmd


def remove_container(name):
	run_command(["sudo", "docker", "stop", name])
	run_command(["sudo", "docker", "rm", name])


# Create functions

def create_compose(directory):
	os.chdir(directory)
	run_command(["sudo", "docker-compose", "up", "--no-start"])
	os.chdir(bot_location)


def create_container(name, arguments, image):
	result, error = run_command(["sudo", "docker", "create", f"--name={name}", arguments, image])
	if error:
		print(result)
		sys.exit(-1)


# Restart functions

def restart_compose(directory):
	os.chdir(directory)
	run_command(["sudo", "docker-compose", "restart"])
	os.chdir(bot_location)


def restart_container(name):
	result, _ = run_command(["sudo", "docker", "restart", name])
	result = result.lower()
	return validate_container_command(result, name)


# Stop functions

def stop_compose(directory):
	os.chdir(directory)
	run_command(["sudo", "docker-compose", "stop"])
	os.chdir(bot_location)


def stop_container(name):
	result, _ = run_command(["sudo", "docker", "stop", name])
	result = result.lower()
	return validate_container_command(result, name)

# Start functions

def start_compose(directory):
	os.chdir(directory)
	run_command(["sudo", "docker-compose", "up", "-d"])
	os.chdir(bot_location)


def start_container(name):
	result, _ = run_command(["sudo", "docker", "start", name])
	result = result.lower()
	return validate_container_command(result, name)


load_dockers()
print("Container information loaded")

if len(sys.argv) >= 2:
	if "init" in sys.argv:
		print("Setting up containers")
		containers = get_all_containers()
		with tqdm.tqdm(total=len(containers)+len(dockers)) as pbar:
			for container in get_all_containers():
				remove_container(container)
				pbar.update(1)

			for chall in dockers:
				if dockers[chall]["type"] == "compose":
					create_compose(dockers[chall]["directory"])
				elif dockers[chall]["type"] == "container":
					c = dockers[chall]
					create_container(c["container-name"], c["create-args"], c["image"])
			pbar.update(1)

	if "start" in sys.argv:
		print("Starting all containers")
		with tqdm.tqdm(total=len(dockers)) as pbar:
			for container in get_all_containers():
				remove_container(container)
				pbar.update(1)

			for chall in dockers:
				if dockers[chall]["type"] == "compose":
					start_compose(dockers[chall]["directory"])
				elif dockers[chall]["type"] == "container":
					c = dockers[chall]
					start_container(c["container-name"])
			pbar.update(1)

	if "bot" not in sys.argv:
		sys.exit()
else:
	print("""Provide one (or more) of the following command line arguments:
	init - remove all preexisting Docker containers and recreate from the Docker container file.
	start - start all Docker containers from the Docker container file
	bot - start the Discord bot""")
	sys.exit()

client.run(token)
