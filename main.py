# TEACUP - RTCP docker management Discord bot
# Forked from milkdrop's Microbot for the XMAS CTF

import os
import subprocess
import logging
import discord
import platform
import asyncio
import requests
import time
import psutil
import json


if os.getuid() != 0:
	print("This script requires root priviledges.")
	exit(-1)

# TODO: Switch to loguru
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename = "discord.log", encoding = "utf-8", mode = "w")
handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(handler)

# Load settings
with open("settings.json") as f:
	settings = json.load(f)

	token = settings["discord-token"]
	adminChannels = settings["channels"]["admin"]
	publicChannels = settings["channels"]["public"]
	maxvotes = settings["restart-votes-required"]
	prefix = settings["command-prefix"]
	presence_text = settings["playing-line"]
	docker_info_file = settings["docker-info-file"]
	docker_defaults = settings["docker-defaults"]

	del settings


client = discord.Client()
restartreq = {}

cmds = {
	"help": "Show this message",
	"challs": "See available challenges",
	"restart chall": "Vote to restart a challenge"
}

cmdsAdmin = {
	"help": "Show this message",
	"refresh": "Refresh challenge database",
	"challenge": "Display challenge server status",
	"platform": "Display platform server status"
}

cmdsDocker = {
	"dockers": "Display all available dockers",
	"running": "Display running dockers",
	"start chall1 chall2 ...": "Start the docker for multiple challenges(chall1, chall2, ...)",
	"stop chall1 ...": "Stop the docker for multiple challenges",
	"restart chall1 ...": "Restart the docker for multiple challenges"
}

cmdsStatus = {
	"status cat1 cat2 ...": "Display docker status from specified categories(cat1, cat2, ...) - Specify no category to display all",
	"statusfull cat1 ...": "Display full docker status from specified categories"
}


# TODO: add commands to PM admins error and command logs
# TODO: add function to log restart actions to another channel

@client.event
async def on_ready():
	print("Ready! Connected as " + client.user.name)
	client.loop.create_task(rotate_statuses())


async def log_usage():
	while True:
		logger.info(formatSysStatus())
		await asyncio.sleep(60 * 30)


@client.event
async def on_message(message):
	global dockers

	if message.author == client.user:
		return

	authorID = message.author.id
	inMsg = message.content.lower().split()

	# If the message content does not start with the command prefix
	if inMsg[0][:len(prefix)] != prefix:
		return

	inMsg[0] = inMsg[0][len(prefix):]  # remove prefix from start of message
	printer = ":gear: "

	# TODO: switch from using channel IDs to using role IDs
	if message.channel.id in publicChannels:  # if the message was sent from a public challenge
		if inMsg[0] == "help":
			printer += "Here are the commands you can run:\n"
			for cmd in cmds:
				printer += "\t**- {}:** `{}`\n".format(cmd, cmds[cmd])
		elif inMsg[0] == "challs":
			f = subprocess.check_output(["docker", "container", "ls"]).decode("UTF-8").strip().split("\n")[1:]

			if len(f) == 0:
				printer += "No Challenges"
			else:
				running = []
				runningData = {}

				for line in f:
					line = line.split()
					line = line[len(line)-1]
					running.append(line)

				printer += "Available challenges:\n"

				for cat in dockers:
					for chall in dockers[cat]:
						if chall in running:
							if cat not in runningData:
								runningData[cat] = []

							runningData[cat].append(chall)

				for cat in runningData:
					printer += "\t**- {}({}):** `".format(cat.upper(), len(runningData[cat]))
					for chall in runningData[cat]:
						printer += chall + " "
					printer += "`\n"

		elif inMsg[0] == "restart":
			name = "".join(inMsg[1:])
			name = resolveName(name)
			challData = getChallenge(name)

			if challData == []:
				printer += "Challenge `{}` does not exist".format(name)
			else:
				if name not in restartreq:
					restartreq[name] = []

				if authorID not in restartreq[name]:
					restartreq[name].append(authorID)

				votes = len(restartreq[name])

				if votes < maxvotes:
					printer += "**{}/{}** votes needed to restart `{}`".format(votes, maxvotes, name)
				else:
					stopDocker(name)
					startDocker(name)
					printer += "Challenge `{}` has been restarted".format(name)
					restartreq[name] = []
		else:
			printer = "Unknown command: `{}`".format(inMsg[0])

		await message.channel.send(printer)

	elif message.channel.id in adminChannels:  # if the message was sent from an admin channel
		if inMsg[0] == "help":
			printer += "Here are the commands you can run:\n"
			for cmd in cmdsAdmin:
				printer += "\t**- {}:** `{}`\n".format(cmd, cmdsAdmin[cmd])

			printer += "\n:gear: Docker Commands:\n"
			for cmd in cmdsDocker:
				printer += "\t**- {}:** `{}`\n".format(cmd, cmdsDocker[cmd])

			printer += "\n:gear: Status Commands:\n"
			for cmd in cmdsStatus:
				printer += "\t**- {}:** `{}`\n".format(cmd, cmdsStatus[cmd])

		elif inMsg[0] == "refresh":
			challenges = load_dockers()s
			printer += "Challenge database has been refreshed"

		elif inMsg[0] == "challenge":
			printer += "Challenge Server Status:\n"
			printer += formatSysStatus()

		elif inMsg[0] == "platform":
			return

		elif inMsg[0] == "dockers":
			printer += "Available dockers:\n"
			for cat in dockers:
				printer += "\t**- {}({}):** `".format(cat.upper(), len(dockers[cat]))

				for chall in dockers[cat]:
					printer += chall + " "

				printer += "`\n"

		elif inMsg[0] == "start" or inMsg[0] == "stop" or inMsg[0] == "restart":
			printer += "Starting Challenges:\n" if inMsg[0] == "start" else "Stopping Challenges:\n"

			for name in inMsg[1:]:
				name = resolveName(name)
				challData = getChallenge(name)

				# TODO: make bot looks like it's typing to signify it's doing something
				# https://discordpy.readthedocs.io/en/latest/api.html#discord.abc.Messageable.typing

				if challData == []:
					printer += "\t**- {}:** `Does not exist`\n".format(name)
				else:
					if inMsg[0] == "stop" or inMsg[0] == "restart":
						stopDocker(name)
					if inMsg[0] == "start" or inMsg[0] == "restart":
						startDocker(name)

					printer += "\t**- {}:** `OK [{}]`\n".format(name, str(challData[1])[1:-1].split(":")[0])

		elif inMsg[0] == "status" or inMsg[0] == "statusfull" or inMsg[0] == "running":
			categories = inMsg[1:]
			f = subprocess.check_output(["docker", "container", "ls"]).decode("UTF-8").strip().split("\n")[1:]

			if len(f) == 0:
				printer += "No Dockers Running."
			else:
				running = []
				runningData = {}

				for line in f:
					line = line.split()
					line = line[len(line) - 1]
					running.append(line)

				printer += "Dockers running:\n"
				total = 0

				for cat in dockers:
					if categories != [] and cat not in categories:
						continue

					for chall in dockers[cat]:
						if chall in running:
							challData = getChallenge(chall)
							if inMsg[0] != "running":
								pid = subprocess.check_output(["docker inspect -f "{{.State.Pid}}" " + chall], shell = True).decode("ASCII").strip()
								numConnections = subprocess.check_output(["nsenter -t {} -n netstat -anp | grep ESTABLISHED | wc -l".format(pid)], shell = True).decode("ASCII").strip()
								total += int(numConnections)
							else:
								numConnections = 0

							if cat not in runningData:
								runningData[cat] = []

							runningData[cat].append([chall, numConnections, challData[1]])

				for cat in runningData:
					printer += "\t**- {}({}):** ".format(cat.upper(), len(runningData[cat]))

					if inMsg[0] == "status":
						printer += "`"
						for chall in runningData[cat]:
							printer += chall[0] + " [{}], ".format(chall[1])
						printer += "`\n"

					elif inMsg[0] == "statusfull":
						printer += "\n"
						for chall in runningData[cat]:
							printer += "\t\t- " + chall[0] + ": `{} Players [{}]`\n".format(chall[1], chall[2])

					elif inMsg[0] == "running":
						printer += "`"
						for chall in runningData[cat]:
							printer += chall[0] + " "
						printer += "`\n"

				if inMsg[0] != "running":
					printer += "\nTotal Connections: **{}**".format(total)
		else:
			printer = "Unknown command: `{}`".format(inMsg[0])

		await message.channel.send(printer)
	# if the message was not sent in any of the channels listed in one of the ID lists nothing is done


def startDocker(name, cpus=docker_defaults["cpus"], memory=docker_defaults["memory"]):
	"""
	Starts a specified docker container using CPU and memory values specified
	"""
	challData = getChallenge(name)
	port = ""
	for portSetting in challData[1]:
		if portSetting != 0:
			port += "-p {}:{} ".format(portSetting, challData[1][portSetting])

	if len(challData) > 2:
		memory = challData[2]

	if len(challData) > 3:
		cpus = challData[3]

	cmd = "docker run -d --cpus="{1}" --memory="{2}m" --name {0} {3} --restart always {0}".format(name, cpus, memory, port)
	os.system(cmd)
	return cmd


def stopDocker(name):
	"""
	Stops a specificed docker container
	"""
	cmd = "docker rm -f {}".format(name)
	os.system(cmd)
	return cmd


def resolveName(name):
	for cat in dockers:
		for docker in dockers[cat]:
			if name == docker[:len(name)]:
				return docker

	return name


def getChallenge(chall):
	for cat in dockers:
		if chall in dockers[cat]:
			return [cat] + dockers[cat][chall]
	return []


def getSysStatus():
	"""
	Gets CPU and memory usage values, as well as the number of connections to the machine
	"""
	mem = psutil.virtual_memory()
	memUsed = round(mem.used /(1024 ** 2))
	memTotal = round(mem.total /(1024 ** 2))

	numConnections = subprocess.check_output(["netstat -anp | grep ESTABLISHED | wc -l"], shell=True).decode("ASCII").strip()

	return {"cpu": round(psutil.cpu_percent(), 2), "memUsed": memUsed, "memTotal": memTotal, "numConnections": numConnections}


def formatSysStatus():
	"""
	Formats the output from getSysStatus into a human readable form
	"""
	sysStatus = getSysStatus()

	output = "**{}%** CPU Usage\n".format(sysStatus["cpu"])
	output += "**{}/{}** MB RAM Used\n".format(sysStatus["memUsed"], sysStatus["memTotal"])
	output += "**{}** Connections\n".format(sysStatus["numConnections"])

	return output


def load_dockers():
	"""
	Returns docker container information from the file specified as docker-info-file in the settings JSON.s
	"""
	# TODO: Change this, it's rubbish
	return eval(open(docker_info_file, "r").read().strip())


async def rotate_statuses():
	while True:
		for status in presence_text:
			await client.change_presence(activity=discord.CustomActivity(presence_text))
			await asyncio.sleep(60)


dockers = load_dockers()

client.loop.create_task(log_usage())
client.run(token)