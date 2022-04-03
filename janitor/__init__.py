import datetime
import logging
import os
from typing import Optional

import discord
from discord.ext import commands, tasks

from .db import isSweepEnabled, addChannel, removeChannel, getAllChannels, setMaxAge, getMaxAge

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

def findChannel(guild: discord.Guild, channel: int):
	match = [x for x in guild.channels if x.id == channel]
	match len(match):
		case 0:
			logging.warning(f"Channel id {channel} does not exist on its guild ({guild!r})")
		case 1:
			return match[0]
		case _:
			logging.error(f"Channel id {channel} is duplicated {len(match)} times in guild {guild!r}")

async def reactionReply(ctx: commands.Context, emoji = "\u2705"):	
	await ctx.message.add_reaction(emoji)

class Janitor(commands.Cog):
	maxBulkDeleteMessages = 100

	def __init__(self, bot):
		self.bot: commands.Bot = bot
		
		self.sweepTask.start()
	
	@tasks.loop(minutes = 1)
	async def sweepTask(self):
		print("sweep task")
	
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
	
	@commands.group(help = "Manage list of channels that should be swept")
	async def channels(self, ctx: commands.Context):
		if ctx.invoked_subcommand is None:	
			raise commands.errors.UserInputError("Expected a subcommand")
	
	@channels.command()
	async def add(self, ctx: commands.Context, channel: discord.TextChannel):
		if isSweepEnabled(channel.id):
			await ctx.reply(f"I am already sweeping {channel.mention}")
		else:
			addChannel(channel.id, ctx.guild.id)
			await reactionReply(ctx)
	
	@channels.command()
	async def remove(self, ctx: commands.Context, channel: discord.TextChannel):
		if not isSweepEnabled(channel.id):
			await ctx.reply(f"I am not currently sweeping {channel.mention}")
		else:
			removeChannel(channel.id)
			await reactionReply(ctx)
	
	@channels.command()
	async def list(self, ctx: commands.Context):
		channels = list(filter(
			lambda x: x is not None,
			(findChannel(ctx.guild, id) for id in getAllChannels(ctx.guild.id))
		))
		if len(channels) > 0:
			channelsStr = "\n\t".join(channel.mention for channel in channels)
			await ctx.reply(f"""In `{ctx.guild.name}` I am configured to sweep:\n\t{channelsStr}""")
		else:
			await ctx.reply(f"I'm not configured to sweep any channels in `{ctx.guild.name}`")
	
	@commands.command()
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
	
	@commands.command()
	async def sweepnow(self, ctx: commands.Context, ignoreAge: Optional[bool] = False):
		if not isSweepEnabled(ctx.channel.id):
			await ctx.reply(f"Sweeping is not enabled for {ctx.channel.mention}")
			return
		
		async with ctx.channel.typing():
			await self.sweepChannel(ctx.channel, ignoreAge)
			if not ignoreAge: # message will have been deleted
				await reactionReply(ctx)

def makeBot():
	intents = discord.Intents.default()
	# intents.message_content = True # FIXME: this needs to be enabled in future discord.py versions
	
	bot = commands.Bot(command_prefix = commands.when_mentioned, intents = intents)
	bot.add_cog(Janitor(bot))
	
	return bot

def main(bot = None):
	logging.basicConfig(level = logging.INFO)
	
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
