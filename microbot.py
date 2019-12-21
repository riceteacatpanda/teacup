import os, subprocess, logging
import discord, platform, asyncio
import requests, time, psutil

if (os.getuid () != 0):
	print ("I need root.")
	exit (-1)

logger = logging.getLogger ("discord")
logger.setLevel (logging.INFO)
handler = logging.FileHandler (filename = "discord.log", encoding = "utf-8", mode = "w")
handler.setFormatter (logging.Formatter ("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler (handler)

client = discord.Client ()
token = open ("token", "r").read ().strip ()
dockers = eval (open ("dockers", "r").read ().strip ())
adminChannels = [523194184140849158]
publicChannels = [655038385513300018]

restartreq = {}
maxvotes = 5

prefix = "!"

cmds = {"help": "Show this message",
		"challs": "See available challenges",
		"restart chall": "Vote to restart a challenge"}

cmdsAdmin = {"help": "Show this message",
			"refresh": "Refresh challenge database",
			"challenge": "Display challenge server status",
			"platform": "Display platform server status"}

cmdsDocker = {"dockers": "Display all available dockers",
				"running": "Display running dockers",
				"start chall1 chall2 ...": "Start the docker for multiple challenges (chall1, chall2, ...)",
				"stop chall1 ...": "Stop the docker for multiple challenges",
				"restart chall1 ...": "Restart the docker for multiple challenges"}

cmdsStatus = {"status cat1 cat2 ...": "Display docker status from specified categories (cat1, cat2, ...) - Specify no category to display all",
				"statusfull cat1 ...": "Display full docker status from specified categories"}

@client.event
async def on_ready ():
	print ('All good! Name: ' + client.user.name)
	await client.change_presence (activity = discord.Game (name = 'What is my purpose? I oversee X-MAS.'))

async def log_usage ():
	while True:
		logger.info (formatSysStatus ())
		await asyncio.sleep (60 * 30)

@client.event
async def on_message (message):
	global dockers

	if (message.author == client.user):
		return

	authorID = message.author.id
	inMsg = message.content.lower().split ()

	if (inMsg[0][:len (prefix)] != prefix):
		return

	inMsg[0] = inMsg[0][len (prefix):]
	printer = ":gear: "

	if (message.channel.id in publicChannels):
		if (inMsg[0] == "help"):
			printer += "Here are the commands you can run:\n"

			for cmd in cmds:
				printer += "\t**- {}:** `{}`\n".format (cmd, cmds[cmd])
		elif (inMsg[0] == "challs"):
			f = subprocess.check_output (["docker", "container", "ls"]).decode ("UTF-8").strip ().split ("\n")[1:]

			if (len (f) == 0):
				printer += "No Challenges"
			else:
				running = []
				runningData = {}

				for line in f:
					line = line.split ()
					line = line [len (line) - 1]
					running.append (line)

				printer += "Available challenges:\n"

				for cat in dockers:
					for chall in dockers[cat]:
						if (chall in running):
							if (cat not in runningData):
								runningData[cat] = []

							runningData[cat].append (chall)

				for cat in runningData:
					printer += "\t**- {} ({}):** `".format (cat.upper (), len (runningData[cat]))
					for chall in runningData[cat]:
						printer += chall + " "
					printer += "`\n"

		elif (inMsg[0] == "restart"):
			name = ''.join (inMsg[1:])
			name = resolveName (name)
			challData = getChallenge (name)

			if (challData == []):
				printer += "Challenge `{}` does not exist".format (name)
			else:
				if (name not in restartreq):
					restartreq[name] = []

				if (authorID not in restartreq[name]):
					restartreq[name].append (authorID)

				votes = len (restartreq[name])

				if (votes < maxvotes):
					printer += "**{}/{}** votes needed to restart `{}`".format (votes, maxvotes, name)
				else:
					stopDocker (name)
					startDocker (name)
					printer += "Challenge `{}` has been restarted".format (name)
					restartreq[name] = []
		else:
			printer = "Unknown command: `{}`".format (inMsg[0])

		await message.channel.send (printer)
	elif (message.channel.id in adminChannels):
		if (inMsg[0] == "help"):
			printer += "Here are the commands you can run:\n"
			for cmd in cmdsAdmin:
				printer += "\t**- {}:** `{}`\n".format (cmd, cmdsAdmin[cmd])

			printer += "\n:gear: Docker Commands:\n"
			for cmd in cmdsDocker:
				printer += "\t**- {}:** `{}`\n".format (cmd, cmdsDocker[cmd])

			printer += "\n:gear: Status Commands:\n"
			for cmd in cmdsStatus:
				printer += "\t**- {}:** `{}`\n".format (cmd, cmdsStatus[cmd])

		elif (inMsg[0] == "refresh"):
			challenges = eval (open ("dockers", "r").read ().strip ())
			printer += "Challenge database has been refreshed"

		elif (inMsg[0] == "challenge"):
			printer += "Challenge Server Status:\n"
			printer += formatSysStatus ()

		elif (inMsg[0] == "platform"):
			return

		elif (inMsg[0] == "dockers"):
			printer += "Available dockers:\n"
			for cat in dockers:
				printer += "\t**- {} ({}):** `".format (cat.upper (), len (dockers[cat]))

				for chall in dockers[cat]:
					printer += chall + " "

				printer += "`\n"

		elif (inMsg[0] == "start" or inMsg[0] == "stop" or inMsg[0] == "restart"):
			printer += "Starting Challenges:\n" if inMsg[0] == "start" else "Stopping Challenges:\n"

			for name in inMsg[1:]:
				name = resolveName (name)
				challData = getChallenge (name)

				if (challData == []):
					printer += "\t**- {}:** `Does not exist`\n".format (name)
				else:
					if (inMsg[0] == "stop" or inMsg[0] == "restart"):
						stopDocker (name)
					if (inMsg[0] == "start" or inMsg[0] == "restart"):
						startDocker (name)

					printer += "\t**- {}:** `OK [{}]`\n".format (name, str (challData[1])[1:-1].split(":")[0])

		elif (inMsg[0] == "status" or inMsg[0] == "statusfull" or inMsg[0] == "running"):
			categories = inMsg[1:]
			f = subprocess.check_output (["docker", "container", "ls"]).decode ("UTF-8").strip ().split ("\n")[1:]

			if (len (f) == 0):
				printer += "No Dockers Running."
			else:
				running = []
				runningData = {}

				for line in f:
					line = line.split ()
					line = line [len (line) - 1]
					running.append (line)

				printer += "Dockers running:\n"
				total = 0

				for cat in dockers:
					if (categories != [] and cat not in categories):
						continue

					for chall in dockers[cat]:
						if (chall in running):
							challData = getChallenge (chall)
							if (inMsg[0] != "running"):
								pid = subprocess.check_output (["docker inspect -f '{{.State.Pid}}' " + chall], shell = True).decode ("ASCII").strip ()
								numConnections = subprocess.check_output (["nsenter -t {} -n netstat -anp | grep ESTABLISHED | wc -l".format (pid)], shell = True).decode ("ASCII").strip ()
								total += int (numConnections)
							else:
								numConnections = 0

							if (cat not in runningData):
								runningData[cat] = []

							runningData[cat].append ([chall, numConnections, challData[1]])

				for cat in runningData:
					printer += "\t**- {} ({}):** ".format (cat.upper (), len (runningData[cat]))

					if (inMsg[0] == "status"):
						printer += "`"
						for chall in runningData[cat]:
							printer += chall[0] + " [{}], ".format (chall[1])
						printer += "`\n"

					elif (inMsg[0] == "statusfull"):
						printer += "\n"
						for chall in runningData[cat]:
							printer += "\t\t- " + chall[0] + ": `{} Players [{}]`\n".format (chall[1], chall[2])

					elif (inMsg[0] == "running"):
						printer += "`"
						for chall in runningData[cat]:
							printer += chall[0] + " "
						printer += "`\n"

				if (inMsg[0] != "running"):
					printer += "\nTotal Connections: **{}**".format (total)
		else:
			printer = "Unknown command: `{}`".format (inMsg[0])

		await message.channel.send (printer)

def startDocker (name, cpus = 0.1, memory = 100):
	challData = getChallenge (name)
	port = ""
	for portSetting in challData[1]:
		if (portSetting != 0):
			port += "-p {}:{} ".format (portSetting, challData[1][portSetting])

	if (len (challData) > 2):
		memory = challData [2]

	if (len (challData) > 3):
		cpus = challData [3]

	cmd = 'docker run -d --cpus="{1}" --memory="{2}m" --name {0} {3} --restart always {0}'.format (name, cpus, memory, port)
	os.system (cmd)
	return cmd

def stopDocker (name):
	cmd = 'docker rm -f {}'.format (name)
	os.system (cmd)
	return cmd

def resolveName (name):
	for cat in dockers:
		for docker in dockers[cat]:
			if (name == docker[:len (name)]):
				return docker

	return name

def getChallenge (chall):
	for cat in dockers:
		if chall in dockers[cat]:
			return [cat] + dockers[cat][chall]

	return []

def getSysStatus ():
	mem = psutil.virtual_memory ()
	memUsed = round (mem.used / (1024 ** 2))
	memTotal = round (mem.total / (1024 ** 2))

	numConnections = subprocess.check_output (["netstat -anp | grep ESTABLISHED | wc -l"], shell = True).decode ("ASCII").strip ()

	return {"cpu": round (psutil.cpu_percent (), 2), "memUsed": memUsed, "memTotal": memTotal, "numConnections": numConnections}

def formatSysStatus ():
	sysStatus = getSysStatus ()

	output = "**{}%** CPU Usage\n".format (sysStatus["cpu"])
	output += "**{}/{}** MB RAM Used\n".format (sysStatus["memUsed"], sysStatus["memTotal"])
	output += "**{}** Connections\n".format (sysStatus["numConnections"])

	return output

client.loop.create_task (log_usage ())
client.run (token)