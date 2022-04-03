import functools
import sqlite3

SCHEMA = """
CREATE TABLE channels(
	id INT PRIMARY KEY NOT NULL,
	guild INT NOT NULL,
	maxAge INT NOT NULL DEFAULT 5
) STRICT;
CREATE INDEX channelsGuild ON channels(guild);
"""
DB_FILE = "janitorbot.db"

db = None
def getDB() -> sqlite3.Connection:
	global db
	if db is None:
		try:
			db = sqlite3.connect(f"file:{DB_FILE}?mode=rw&cache=shared", uri = True)
		except:
			db = sqlite3.connect(f"file:{DB_FILE}?cache=shared", uri = True)
			db.executescript(SCHEMA)
	return db

def withDB(fn):
	@functools.wraps(fn)
	def inner(*args, **kwargs):
		db = getDB()
		cursor = db.cursor()
		try:
			return fn(db, cursor, *args, **kwargs)
		finally:
			cursor.close()
	return inner

@withDB
def isSweepEnabled(db, cursor: sqlite3.Cursor, channel: int):
	with db:	
		return bool(cursor.execute("SELECT count(id) > 0 FROM channels WHERE id = ?", [channel]).fetchone()[0])

@withDB
def addChannel(db, cursor, channel: int, guild: int):
	with db:	
		cursor.execute("INSERT INTO channels(id, guild) VALUES(?, ?)", [channel, guild])

@withDB
def removeChannel(db, cursor, channel: int):
	with db:	
		cursor.execute("DELETE FROM channels WHERE id = ?", [channel])

@withDB
def getAllChannels(db, cursor, guild: int):
	with db:	
		rows = cursor.execute("SELECT id FROM channels WHERE guild = ?", [guild]).fetchall()
		return [x[0] for x in rows]

@withDB
def setMaxAge(db, cursor, channel: int, maxAgeMinutes: int):
	with db:	
		cursor.execute("UPDATE channels SET maxAge = ? WHERE id = ?", [maxAgeMinutes, channel])

@withDB
def getMaxAge(db, cursor, channel: int):
	with db:	
		row = cursor.execute("SELECT maxAge FROM channels WHERE id = ?", [channel]).fetchone()
		return row[0] if row else 5
