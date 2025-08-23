import spacy
import random
import asyncio
import logging
import time
import os
from poolguy.storage import loadJSON
from poolguy import CommandBot, Alert, rate_limit, command

logger = logging.getLogger(__name__)

nlp = spacy.load("en_core_web_sm")

def replace_random_noun_chunk(text, replacement="these walnuts"):
    """Uses spacy to find all noun 'chunks' <text>. Then replaces a random noun chunk with the <replacement>. Returns result as string"""
    doc = nlp(text)
    noun_chunks = list(doc.noun_chunks)
    if not noun_chunks:
        out = None
    else:
        to_replace = random.choice(noun_chunks)
        start = to_replace.start_char
        end = to_replace.end_char
        out = text[:start] + replacement + text[end:]
        if out.strip() == replacement.strip():
            out = None
    logger.debug(f"[replace_random_noun_chunk] {text} -> {out}")
    return out

class ChannelChatMessageAlert(Alert):
    store = False
    queue_skip = True
    """channel.chat.message"""
    async def process(self):
        if int(self.bot.http.user_id) == int(self.data["chatter_user_id"]):
            return
        if await self.bot.command_check(self.data):
            return
        if await self.bot._get_ignore_status(self.data["chatter_user_id"]):
            return
        try:
            r = await self.bot.makeJoke(self.data)
            if r:
                m = await self.bot.send_chat(r, self.data["broadcaster_user_id"])
                logger.info(f'{self.data["broadcaster_user_login"]}: {r} {m}')
        except:
            logger.exception(f"Error in process_message():\n")
            raise

class DeezBot(CommandBot):
    def __init__(self, jdelay=[4,15], jlimit=20, loop_delay=300, *args, **kwargs):
        # Fetch sensitive data from environment variables
        client_id = os.getenv("DEEZ_CLIENT_ID")
        client_secret = os.getenv("DEEZ_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ValueError("Environment variables DEEZ_CLIENT_ID and DEEZ_CLIENT_SECRET are required")
        kwargs['client_id'] = client_id
        kwargs['client_secret'] = client_secret
        super().__init__(*args, **kwargs)
        self.jdelay = jdelay
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)
        self.loop_delay = loop_delay
        self.jlimit = jlimit
        self.lastjoke = 0

    def _resetjcount(self):
        self.lastjoke = 0
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)

    async def get_jemote(self, u_id):
        chans = await self._get_channel_list()
        if u_id in chans:
           return chans[u_id]["jemote"]
        return "Kappa"

    async def makeJoke(self, data):
        message = data['message']['text']
        u_id = data["broadcaster_user_id"]
        self.jcount += 1
        # keep from spamming jokes if keywords are being used
        jokes = await self._get_jokes()
        if time.time() - self.lastjoke >= self.jlimit:
            emote = await self.get_jemote(u_id)
            for key, joke in jokes.items():
                if key in message.lower():
                    self._resetjcount()
                    return f"{joke}! {emote}"
        # make random joke
        if self.jcount >= self.jcountmax:
            emote = await self.get_jemote(u_id)
            r = replace_random_noun_chunk(message, "deez nutz")
            if r:
                self._resetjcount()
                return f"{r} {emote}"

    async def _update_user_ignore(self, user_id, ignore):
        await self.storage.insert("ignore", {"user_id": user_id, "ignore": ignore})
    
    async def _get_ignore_status(self, user_id):
        r = await self.storage.query("ignore", where="user_id = ?", params=(user_id,))
        try:
            return r[0]["ignore"]
        except:
            return False

    async def _update_channel_list(self, user_id, config={}):
        if config == False:
            await self.storage.delete("channels", where="user_id = ?", params=(user_id,))
        else:
            await self.storage.insert("channels", {"user_id": user_id, **config})

    async def _get_channel_list(self):
        r = await self.storage.query("channels")
        return {row["user_id"]: row for row in r}
    
    async def _get_jokes(self):
        r = await self.storage.query("joke")
        return {row["keyword"]: row["joke"] for row in r}
    
    def _is_channel_owner(self, user, channel):
        return int(channel["broadcaster_id"]) == int(user["user_id"])
    
    def _is_own_channel(self, user, channel):
        return int(channel["broadcaster_id"]) == int(self.http.user_id)

    @command(name="jemote")
    @rate_limit(calls=1, period=15)
    async def cmd_jemote(self, user, channel, args):
        """ Changes the jemote for the channel or user calling the command """
        if self._is_channel_owner(user, channel) or self._is_own_channel(user, channel):
            emote = args[0]
            try:
                await self._update_channel_list(user["user_id"], config={"jemote": emote})
                await self.send_chat(
                        f"{emote} I like it @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f"Changed {user["username"]} emote: {emote}")
            except:
                logger.exception(f"\n")

    @command(name="join")
    @rate_limit(calls=1, period=15)
    async def cmd_join(self, user, channel, args):
        """ Adds the user calling the command to the channel list """
        if self._is_own_channel(user, channel):
            try:
                await self._update_channel_list(user["user_id"], config={
                        "jemote": "Kappa"
                    })
                await self.send_chat(
                        f":3 @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f"Joining channel: {user["user_id"]}({user["username"]})")
            except:
                logger.exception(f"\n")

    @command(name="leave")
    @rate_limit(calls=1, period=15)
    async def cmd_leave(self, user, channel, args):
        """ Removes the bot from the channel if the channel owner calls the command """
        if self._is_channel_owner(user, channel) or self._is_own_channel(user, channel):
            try:
                await self._update_channel_list(user["user_id"], config=False)
                await self.send_chat(
                        f"PeaceOut @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f"Leaving channel: {user["user_id"]}({user["username"]})")
            except:
                logger.exception(f"\n")

    @command(name="ignore")
    @rate_limit(calls=1, period=15)
    async def cmd_ignore(self, user, channel, args):
        """ Adds the user calling the command to the ignore list """
        try:
            await self._update_user_ignore(user["user_id"], True)
            await self.send_chat(
                    f"I'm notListening to you @{user['username']}", 
                    channel["broadcaster_id"]
                )
            logger.info(f"Added {user["user_id"]}({user["username"]}) to ignore list")
        except:
            logger.exception(f"\n")

    @command(name="unignore")
    @rate_limit(calls=1, period=15)
    async def cmd_unignore(self, user, channel, args):
        """ Removes the calling user from the ignore list """
        try:
            await self._update_user_ignore(user["user_id"], False)
            await self.send_chat(
                        f"I'm Listening to you @{user['username']}", 
                        channel["broadcaster_id"]
                    )
            logger.info(f"Removed {user["user_id"]}({user['username']}) from ignore list")
        except:
            logger.exception(f"\n")

    #===================================================================================
    #===================================================================================
    async def after_login(self):
        await self.add_task(self.deez_loop)
        
    async def deez_loop(self):
        logger.debug(f'deez_loop started')
        await asyncio.sleep(5)
        while self.loop_delay:
            await self.check_connections()
            await asyncio.sleep(self.loop_delay)
        logger.warning(f'deez_loop stopped')
    #===================================================================================
    #===================================================================================

    async def connected_channels(self):
        r = await self.http.getEventSubs(status='enabled')
        return {str(i["condition"]["broadcaster_user_id"]): i for i in r['data']}
    
    async def check_connections(self):
        connnected_channels = await self.connected_channels()
        connected_ids = set(connnected_channels.keys())
        logger.warning(f"Current connections:\n{connected_ids}")
        l = await self._get_channel_list()
        live_r = await self.http.getStreams(user_id=list(l.keys()), type='live') if l else []
        live_list = [chan["user_id"] for chan in live_r]
        live_list += [str(self.http.user_id)]
        disconnect_from = list(connected_ids - set(live_list))
        connect_to = list(set(live_list) - connected_ids)
        if disconnect_from:
            for chan_id in disconnect_from:
                if chan_id == str(self.http.user_id):
                    continue
                r = await self.http.deleteEventSub(connnected_channels[chan_id]['id'])
                if not r:
                    logger.error(f"Couldn't disconnect from {connnected_channels[chan_id]}")
            logger.warning(f"Disconnected from:\n{disconnect_from}")
        if connect_to:
            for chan_id in connect_to:
                try:
                    r = await self.ws.create_event_sub('channel.chat.message', chan_id)
                except:
                    logger.exception(f"Couldn't connect to {chan_id}:\n")
            logger.warning(f"Connected to:\n{connect_to}")


if __name__ == '__main__':
    from rich.logging import RichHandler
    logging.basicConfig(
        format='%(message)s',
        datefmt="%X",
        level=logging.INFO,
        handlers=[RichHandler(rich_tracebacks=True)]
    )
    cfg = loadJSON('cfg.json')
    cfg['alert_objs'] = {'channel.chat.message': ChannelChatMessageAlert}
    bot = DeezBot(**cfg)
    asyncio.run(bot.start(paused=True))
