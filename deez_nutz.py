import spacy
import random
import json
import asyncio
import webbrowser
import time
import os
from poolguy.utils import loadJSON, saveJSON, ctxt
from poolguy import CommandBot, Alert, ColorLogger, rate_limit, command

logger = ColorLogger(__name__)

nlp = spacy.load("en_core_web_sm")

class ChannelChatMessageAlert(Alert):
    store = False
    queue_skip = True
    """channel.chat.message"""
    async def process(self):
        logger.debug(f'{self.data}')
        text = self.data["message"]["text"]
        logger.info(f'[Chat] {self.data["chatter_user_name"]}: {text}', 'purple')
        r = await self.bot.command_check(self.data)
        if r:
            # it was a command, dont make a joke
            return
        try:
            r = await self.bot.makeJoke(text, self.data["chatter_user_name"])
            if r:
                m = await self.bot.send_chat(r, self.data["broadcaster_user_id"])
                logger.debug(f'Sent message response: {r} {m}')
        except Exception as e:
            logger.error(f"Error in process_message(): {e}")
            raise

class DeezBot(CommandBot):
    def __init__(self, jnoun='butt', jemote='Kappa', jpath='db/jokes.json', jdelay=[4,15], jlimit=20, igpath='db/ignore.json', loop_delay=300, always_connect=[], *args, **kwargs):
        # Fetch sensitive data from environment variables
        client_id = os.getenv("DEEZ_CLIENT_ID")
        client_secret = os.getenv("DEEZ_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ValueError("Environment variables DEEZ_CLIENT_ID and DEEZ_CLIENT_SECRET are required")
        kwargs['client_id'] = client_id
        kwargs['client_secret'] = client_secret
        
        super().__init__(*args, **kwargs)
        self.jnoun = jnoun
        self.jemote = jemote
        self.jdelay = jdelay
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)
        self.igpath = igpath
        self.jokes = loadJSON(jpath)
        self.ignoreList = set(loadJSON(self.igpath))
        self.always_connect = always_connect
        self.loop_delay = loop_delay
        self.jlimit = jlimit
        self.lastjoke = 0

    async def send_chat(self, message, channel_id=None):
        r = await self.http.sendChatMessage(message, channel_id)
        r = r[0]
        logger.info(f'{r}')
        if not r['is_sent']:
            logger.error(f"Message not sent! Reason: {r['drop_reason']}")
        return r
        
    @command
    @rate_limit(calls=1, period=30)
    async def cmd_ignore(self, user, channel, args):
        """Adds the user calling the command to the ignore list"""
        try:
            target_user = user["username"].lower()
            if not target_user in self.ignoreList:
                self.ignoreList.add(target_user)
                saveJSON(list(self.ignoreList), self.igpath)
                r = await self.send_chat(
                        f"You will be ignored, @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f"Added {target_user} to ignore list")
        except Exception as e:
            logger.error(f"Error saving ignore list: {e}")
            
    @command
    @rate_limit(calls=1, period=30)
    async def cmd_unignore(self, user, channel, args):
        """Removes the calling user from the ignore list"""
        try:
            target_user = user["username"].lower()
            if target_user in self.ignoreList:
                self.ignoreList.remove(target_user)
                saveJSON(list(self.ignoreList), self.igpath)
                r = await self.send_chat(
                        f"I am listening to you again, @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f"Removed {target_user} from ignore list")
        except Exception as e:
            logger.error(f"Error saving ignore list: {e}")

    #===================================================================================
    #===================================================================================
    async def deez_loop(self):
        logger.warning(f'deez_loop started')
        await asyncio.sleep(20)
        while self.ws._running:
            await self.check_connections()
            await asyncio.sleep(self.loop_delay)
        logger.warning(f'deez_loop stopped')

    async def after_login(self):
        await self.add_task(self.deez_loop)
        self.always_connect.append(str(self.http.user_id))

    async def connected_channels(self):
        r = await self.http.getEventSubs(status='enabled')
        conn_chats = {}
        for i in r['data']:
            if i["type"] == "channel.chat.message":
                conn_chats[str(i["condition"]["broadcaster_user_id"])] = i
        return conn_chats
    
    async def live_follower_ids(self):
        data = await self.http.getChannelFollowers()
        return await self.http.getStreams(user_id=[i['user_id'] for i in data], type='live')
    
    async def check_connections(self):
        connnected_channels = await self.connected_channels()
        connected_ids = set(connnected_channels.keys())
        logger.info(f'Connected to: {json.dumps(list(connnected_channels.keys()))}')
        # get live followers ids
        follower_list = await self.live_follower_ids()
        # Extract just the user_ids from the follower data if it's a list of dicts
        if follower_list and isinstance(follower_list[0], dict):
            follower_list = [str(follower['user_id']) for follower in follower_list]
        # Add the bot's own user_id and others to the set
        live_followers = set(follower_list + self.always_connect)
        # Calculate differences
        cs_diff = list(connected_ids - live_followers)
        # disconnect from those that unfollowed or offline
        if cs_diff:
            for i in cs_diff:
                if i == str(self.http.user_id):
                    # dont disconnect from self
                    continue
                r = await self.http.deleteEventSub(connnected_channels[i]['id'])
                if not r:
                    logger.error(f"Couldn't unsub from {connnected_channels[i]}")
            logger.warning(f'Parted channels: {json.dumps(cs_diff)}')
        
        fs_diff = list(live_followers - connected_ids)
        # connect to the channels we arent already connected to
        if fs_diff:
            for i in fs_diff:
                try:
                    r = await self.ws.create_event_sub('channel.chat.message', i)
                except Exception as e:
                    logger.error(f"Couldn't connect to {i}: {str(e)}")
            logger.warning(f'Joined channels: {json.dumps(fs_diff)}')

    def resetjcount(self):
        self.lastjoke = time.time()
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)

    #why is the function using "these walnuts"? is there an encapsulated method elsewhere that converts "these walnuts" to "deez nutz"? 
    def replace_random_noun_chunk(self, text, replacement="these walnuts"):
        doc = nlp(text)
        noun_chunks = list(doc.noun_chunks)
        if not noun_chunks:
            out = None
        else:
            to_replace = random.choice(noun_chunks)
            
            if len(noun_chunks) > 1 && noun_chunks.index(0) == doc[0:len(to_replace)]:
                del noun_chunks[0]
                to_replace = random.choice(noun_chunks)
                
            start = to_replace.start_char
            end = to_replace.end_char
            out = text[:start] + replacement + text[end:]
            if out.strip() == replacement.strip():
                out = None
        logger.debug(f"[replace_random_noun_chunk] {text} -> {out}")
        return out
    
    async def makeJoke(self, m, user):
        if user.lower() in self.ignoreList:
            logger.debug(f"Ignored message from {user}")
            return
        self.jcount += 1
        # keep from spamming jokes if keywords are being used
        if time.time() - self.lastjoke >= self.jlimit:
            for key in self.jokes:
                if key in m.lower():
                    self.resetjcount()
                    return f"{self.jokes[key]}! {self.jemote}"
        # make random joke
        if self.jcount >= self.jcountmax:
            r = self.replace_random_noun_chunk(m, self.jnoun)
            if r:
                self.resetjcount()
                return f"{r}"


if __name__ == '__main__':
    import logging
    fmat = ctxt('%(asctime)s', 'yellow', style='d') + '-%(levelname)s-' + ctxt('[%(name)s]', 'purple', style='d') + ctxt(' %(message)s', 'green', style='d')
    logging.basicConfig(
        format=fmat,
        datefmt="%I:%M:%S%p",
        level=logging.INFO
    )
    cfg = loadJSON('cfg.json')
    bot = DeezBot(**cfg, alert_objs={'channel.chat.message': ChannelChatMessageAlert})
    asyncio.run(bot.start())

    
