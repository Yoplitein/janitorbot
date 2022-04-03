import datetime
import logging
import os

import discord
from discord.ext import commands, tasks

async def reactionReply(ctx: commands.Context, emoji = "\u2705"):	
	await ctx.message.add_reaction(emoji)

class Janitor(commands.Cog):
	def __init__(self, bot):
		self.bot: commands.Bot = bot
		
		self.sweepTask.start()
	
	@tasks.loop(minutes = 1)
	async def sweepTask(self):
		print("sweep task")
	
	async def sweepChannel(self, channel: discord.TextChannel):
		now = datetime.datetime.utcnow()
		td = datetime.timedelta(minutes=1)
		
		await self.bot.change_presence(
			status = discord.Status.dnd,
			activity = discord.Activity(name = f"messages go poof in #{channel.name}", type = discord.ActivityType.watching),
		)
		
		msg: discord.Message
		queue = []
		async for msg in channel.history(limit = 1000):
			# total += 1
			if msg.pinned: continue
			
			age = now - msg.created_at
			if age < td: continue
			
			if len(queue) >= 90:
				await channel.delete_messages(queue)
				queue.clear()
			queue.append(msg)
		await channel.delete_messages(queue)
		
		await self.bot.change_presence(status = discord.Status.online, activity = None)
	
	@commands.group(help = "Manage list of channels that should be swept")
	async def channel(self, ctx: commands.Context):
		if ctx.invoked_subcommand is None:	
			await ctx.reply("hmm")
	
	@channel.command()
	async def add(self, ctx: commands.Context, channel: discord.TextChannel):
		await ctx.reply(f"todo1 {channel}")
	
	@channel.command()
	async def remove(self, ctx: commands.Context, channel: discord.TextChannel):
		await ctx.reply(f"todo2 {channel}")
	
	@channel.command()
	async def list(self, ctx: commands.Context):
		await ctx.reply("todo3")
	
	@commands.command()
	async def maxage(self, ctx: commands.Context, ageSeconds: int):
		await ctx.reply(f"todo4 {ageSeconds}")
	
	@commands.command()
	async def sweepnow(self, ctx: commands.Context):
		await self.sweepChannel(ctx.channel)
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
