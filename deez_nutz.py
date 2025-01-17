import spacy
from poolguy.utils import random, json, asyncio, webbrowser, time, os
from poolguy.utils import loadJSON, saveJSON, cmd_rate_limit, ctxt
from poolguy.twitch import CommandBot, Alert, ColorLogger

logger = ColorLogger(__name__)

nlp = spacy.load("en_core_web_sm")

class ChannelChatMessageAlert(Alert):
    """channel.chat.message"""
    async def process(self):
        logger.debug(f'{self.data}')
        text = self.data["message"]["text"]
        user = {
            "user_id": self.data["chatter_user_id"], 
            "username": self.data["chatter_user_name"]
            }
        channel = {
            "broadcaster_id": self.data["broadcaster_user_id"],
            "broadcaster_user_name": self.data["broadcaster_user_name"]
            }
        logger.info(f'[Chat] {user["username"]}: {text}', 'purple')
        if str(user["user_id"]) == str(self.bot.http.user_id):
            logger.debug(f'Own message ignored')
            return
        if self.data["source_broadcaster_user_id"]:
            logger.debug(f'Shared chat message ignored')
            return
        c = await self.bot.command_check(text, user, channel)
        if c:
            return
        if user["username"].lower() in self.bot.ignoreList:
            logger.debug(f"Ignored message from {user['username']}")
            return
        try:
            r = await self.bot.makeJoke(text)
            if r:
                await self.bot.http.sendChatMessage(r, broadcaster_id=channel["broadcaster_id"])
                logger.debug(f'Sent message response: {r}')
        except Exception as e:
            logger.error(f"Error in process_message(): {e}")
            raise

class DeezBot(CommandBot):
    def __init__(self, jnoun='butt', jemote='Kappa', jpath='db/jokes.json', 
            jdelay=[4,15], jlimit=20, igpath='db/ignore.json', loop_delay=300, *args, **kwargs):
        # Fetch sensitive data from environment variables
        client_id = os.getenv("DEEZ_CLIENT_ID")
        client_secret = os.getenv("DEEZ_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ValueError("Environment variables DEEZ_CLIENT_ID and DEEZ_CLIENT_SECRET are required")
        kwargs['http_config']['client_id'] = client_id
        kwargs['http_config']['client_secret'] = client_secret
        
        super().__init__(*args, **kwargs)
        self.jnoun = jnoun
        self.jemote = jemote
        self.jdelay = jdelay
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)
        self.igpath = igpath
        self.jokes = loadJSON(jpath)
        self.ignoreList = set(loadJSON(self.igpath))
        self.loop_delay = loop_delay
        self.jlimit = jlimit
        self.lastjoke = 0

    @cmd_rate_limit(calls=1, period=30)
    async def cmd_ignore(self, user, channel, args):
        """Adds the user calling the command to the ignore list"""
        try:
            target_user = user["username"].lower()
            if not target_user in self.ignoreList:
                self.ignoreList.add(target_user)
                saveJSON(list(self.ignoreList), self.igpath)
                await self.http.sendChatMessage(
                        f"You will be ignored, @{user['username']}", 
                        broadcaster_id=channel["broadcaster_id"]
                    )
                logger.info(f"Added {target_user} to ignore list")
        except Exception as e:
            logger.error(f"Error saving ignore list: {e}")
    
    @cmd_rate_limit(calls=1, period=30)
    async def cmd_unignore(self, user, channel, args):
        """Removes the calling user from the ignore list"""
        try:
            target_user = user["username"].lower()
            if target_user in self.ignoreList:
                self.ignoreList.remove(target_user)
                saveJSON(list(self.ignoreList), self.igpath)
                await self.http.sendChatMessage(
                        f"I am listening to you again, @{user['username']}", 
                        broadcaster_id=channel["broadcaster_id"]
                    )
                logger.info(f"Removed {target_user} from ignore list")
        except Exception as e:
            logger.error(f"Error saving ignore list: {e}")
            
    def register_routes(self):
        @self.app.route('/')
        async def index():
            return "DEEZ NUTZ"

    #===================================================================================
    #===================================================================================
    async def deez_loop(self):
        logger.warning(f'deez_loop started')
        await asyncio.sleep(20)
        while self.ws.connected:
            await self.check_connections()
            await asyncio.sleep(self.loop_delay)
        logger.warning(f'deez_loop stopped')

    async def after_login(self):
        await self.add_task(self.deez_loop)

    async def connected_channels(self):
        r = await self.http.getEventSubs(status='enabled')
        conn_chats = {}
        for i in r['data']:
            if i["type"] == "channel.chat.message":
                conn_chats[str(i["condition"]["broadcaster_user_id"])] = i
        return conn_chats
    
    async def live_follower_ids(self):
        data = await self.http.getChannelFollowers(first=100)
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
        # Add the bot's own user_id to the set
        live_followers = set(follower_list + [str(self.http.user_id)])
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
            logger.warning(f'Parted channels: \n{json.dumps(cs_diff)}')
        
        fs_diff = list(live_followers - connected_ids)
        # connect to the channels we arent already connected to
        if fs_diff:
            for i in fs_diff:
                try:
                    r = await self.http.createEventSub('channel.chat.message', self.ws.session_id, i)
                except Exception as e:
                    logger.error(f"Couldn't connect to {i}: {str(e)}")
            logger.warning(f'Joined channels: \n{json.dumps(fs_diff)}')

    def resetjcount(self):
        self.lastjoke = time.time()
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)
    
    def replace_random_noun_chunk(self, text, replacement="these walnuts"):
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
    
    async def makeJoke(self, m):
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
    