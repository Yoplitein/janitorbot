import asyncio
import datetime
import logging
import os
from typing import List, Optional

import discord
from discord.ext import commands, tasks

from .db import isSweepEnabled, addChannel, removeChannel, getAllChannels, setMaxAge, getMaxAge

EMOJI_CHECK = "\u2705"
EMOJI_CROSS = "\u274E"
EMOJI_STOP = "\u23F9"
EMOJI_POOP = "\U0001F4A9"

def maxAgeRepr(maxAge):
	seconds = maxAge * 60
	days, seconds = divmod(seconds, 24 * 60 * 60)
	hours, seconds = divmod(seconds, 60 * 60)
	minutes, seconds = divmod(seconds, 60)
	
	ret = []
	if days > 0: ret.append(f"{days} days")
	if hours > 0: ret.append(f"{hours} hours")
	if minutes > 0 or len(ret) == 0: ret.append(f"{minutes} minutes")
	return ", ".join(ret)

def findChannel(guild: discord.Guild, channelID: int):
	match = [x for x in guild.channels if x.id == channelID]
	match len(match):
		case 0:
			logging.warning(f"Channel id {channelID} does not exist on its guild ({guild!r})")
		case 1:
			return match[0]
		case _:
			logging.error(f"Channel id {channelID} is duplicated {len(match)} times in guild {guild!r}")

def findChannels(guild: discord.Guild, channelIDs: List[int]):
	return list(filter(
		lambda x: x is not None,
		(findChannel(guild, id) for id in channelIDs)
	))

async def reactionReply(ctx: commands.Context, emoji = EMOJI_CHECK):
	await ctx.message.add_reaction(emoji)

class Janitor(commands.Cog):
	maxBulkDeleteMessages = 100

	def __init__(self, bot):
		self.bot: commands.Bot = bot
		
		self.sweepTask.start()
	
	@tasks.loop(minutes = 1)
	async def sweepTask(self):
		logging.debug("Running sweep task")
		
		for guild in self.bot.guilds:
			channels = findChannels(guild, getAllChannels(guild.id))
			logging.debug(f"Sweeping {len(channels)} channels in guild `{guild.name}`")
			
			for channel in channels:
				logging.debug(f" => Sweeping `#{channel.name}`")
				await self.sweepChannel(channel)
	
	@sweepTask.before_loop
	async def beforeSweepTask(self):
		await self.bot.wait_until_ready()
	
	async def sweepChannel(self, channel: discord.TextChannel, ignoreAge = False):
		now = datetime.datetime.utcnow()
		maxAge = datetime.timedelta(minutes = getMaxAge(channel.id))
		
		await self.bot.change_presence(
			status = discord.Status.dnd,
			activity = discord.Activity(name = f"messages go poof in #{channel.name}", type = discord.ActivityType.watching),
		)
		
		msg: discord.Message
		queue = []
		async for msg in channel.history(limit = None):
			if msg.pinned: continue
			
			age = now - msg.created_at
			if not ignoreAge and age < maxAge: continue
			
			if len(queue) == self.maxBulkDeleteMessages:
				await channel.delete_messages(queue)
				queue.clear()
			queue.append(msg)
		await channel.delete_messages(queue) # flush remainder
		
		await self.bot.change_presence(status = discord.Status.online, activity = None)
	
	async def cog_check(self, ctx: commands.Context):
		if ctx.author.guild_permissions.administrator:
			return True
		raise commands.errors.MissingPermissions(["administrator"])
	
	@commands.group(help = "Manage list of channels that should be swept")
	async def channels(self, ctx: commands.Context):
		if ctx.invoked_subcommand is None:	
			raise commands.errors.UserInputError("Expected a subcommand")
	
	@channels.command(help = "Add a channel to be swept")
	async def add(self, ctx: commands.Context, channel: discord.TextChannel):
		if isSweepEnabled(channel.id):
			await ctx.reply(f"I am already sweeping {channel.mention}")
		else:
			addChannel(channel.id, ctx.guild.id)
			await reactionReply(ctx)
	
	@channels.command(help = "Remove a channel from sweep list")
	async def remove(self, ctx: commands.Context, channel: discord.TextChannel):
		if not isSweepEnabled(channel.id):
			await ctx.reply(f"I am not currently sweeping {channel.mention}")
		else:
			removeChannel(channel.id)
			await reactionReply(ctx)
	
	@channels.command(help = "Show all channels in this server being swept")
	async def list(self, ctx: commands.Context):
		channels = findChannels(getAllChannels(ctx.guild.id))
		if len(channels) > 0:
			channelsStr = "\n\t".join(channel.mention for channel in channels)
			await ctx.reply(f"""In `{ctx.guild.name}` I am configured to sweep:\n\t{channelsStr}""")
		else:
			await ctx.reply(f"I'm not configured to sweep any channels in `{ctx.guild.name}`")
	
	@commands.command(help = "Get/set age (in minutes) of messages which should be swept, for current channel")
	async def maxage(self, ctx: commands.Context, ageMinutes: Optional[int]):
		if not isSweepEnabled(ctx.channel.id):
			await ctx.reply(f"Sweeping is not enabled for {ctx.channel.mention}")
			return
		
		maxAge = None
		if ageMinutes is None:
			maxAge = getMaxAge(ctx.channel.id)
		else:
			maxAge = max(1, ageMinutes)
			setMaxAge(ctx.channel.id, maxAge)
		await ctx.reply(f"Messages in {ctx.channel.mention} will be deleted after {maxAgeRepr(maxAge)}")
	
	@commands.command(help = "Sweep the current channel immediately, optionally ignoring message ages")
	async def sweepnow(self, ctx: commands.Context, ignoreAge: Optional[bool] = False):
		if not isSweepEnabled(ctx.channel.id):
			await ctx.reply(f"Sweeping is not enabled for {ctx.channel.mention}")
			return
		
		if ignoreAge:
			confirmMsg = await ctx.reply(f"Are you sure you want to delete **all unpinned messages** in {ctx.channel.mention}, regardless of age?")
			await confirmMsg.add_reaction(EMOJI_CHECK)
			await confirmMsg.add_reaction(EMOJI_CROSS)
			
			try:
				reaction, _ = await self.bot.wait_for(
					"reaction_add",
					timeout = 15,
					check = lambda reaction, user:
						user == ctx.message.author and str(reaction.emoji) in [EMOJI_CHECK, EMOJI_CROSS]
				)
			except asyncio.TimeoutError:
				await reactionReply(ctx, EMOJI_POOP)
				return
			finally:
				await confirmMsg.delete()
			
			if reaction.emoji.encode() != EMOJI_CHECK.encode():
				await reactionReply(ctx, EMOJI_STOP)
				return
		
		async with ctx.channel.typing():
			await self.sweepChannel(ctx.channel, ignoreAge)
			if not ignoreAge: # message will have been deleted
				await reactionReply(ctx)

async def onCommandError(ctx: commands.Context, error: commands.errors.CommandError):
	logging.info(f"onCommandError handling uncaught exception", exc_info = error, stack_info = True)
	await reactionReply(ctx, EMOJI_POOP) # oopsie poopsie
	
	if isinstance(error, commands.errors.CommandNotFound):
		await ctx.reply(f"{error.args[0]}")
		await ctx.send_help()
	elif isinstance(error, commands.errors.UserInputError):
		await ctx.reply(f"{error.args[0]}")
		if ctx.command: await ctx.send_help(ctx.command)
		elif ctx.cog: await ctx.send_help(ctx.cog)
	elif isinstance(error, commands.errors.MissingPermissions):
		await ctx.reply(f"{error.args[0]}")
	elif isinstance(error, commands.errors.CommandInvokeError):
		await ctx.reply("Oopsie poopsie! I had a stroke trying to process that")

def makeBot():
	intents = discord.Intents.default()
	# intents.message_content = True # FIXME: this needs to be enabled in future discord.py versions
	
	bot = commands.Bot(
		command_prefix = commands.when_mentioned,
		intents = intents,
		description = "Deletes old messages from certain channels."
	)
	bot.on_command_error = onCommandError
	bot.add_cog(Janitor(bot))
	
	return bot

def main(bot = None, logLevel = logging.WARNING):
	logging.basicConfig(level = logLevel)
	
	bot = bot or makeBot()
	
	token = None
	try:
		token = os.environ["BOT_TOKEN"]
	except KeyError:
		try:
			with open("token.txt", "r") as f:
				token = f.read().strip()
		except IOError:
			print("Need bot token to run!", file = os.sys.stderr)
			print("Define BOT_TOKEN in environment, or create token.txt in working directory", file = os.sys.stderr)
			raise SystemExit(1)
	bot.run(token)
