import logging, json, time, re
import asyncio, requests, random
import spacy
from twitchio.ext import commands

logger = logging.getLogger(__name__)

nlp = spacy.load("en_core_web_sm")

def loadJSON(filename):
    """ Load json file """
    with open(filename, 'r') as f:
        out = json.load(f)
        logger.debug(f"[loadJSON] {filename} -> {out}")
        return out

def saveJSON(data, filename):
    """ Save data as json to a file """
    with open(filename, 'w') as f:
        out = json.dump(data, f, indent=4)
        logger.debug(f"[saveJSON] {filename} -> {out}")
        return out

cfg = loadJSON("config.json")

def replace_random_noun_chunk(text, replacement="these walnuts"):
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

def parse_url(url):
    pattern = re.compile(r'^(?:(?P<scheme>https?)://)?(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<route>.*)$')
    match = pattern.match(url)
    if match:
        scheme = match.group('scheme') or 'http'
        host = match.group('host')
        port = match.group('port') or (443 if scheme == 'https' else 80)
        route = match.group('route')
        return {
            'scheme': scheme,
            'host': host,
            'port': int(port),
            'route': route
        }
    else:
        raise ValueError("Invalid URL format")

#====================================================
# Twitch stuff ======================================
#====================================================
oauthLink = f"https://id.twitch.tv/oauth2/authorize?client_id={cfg['client_id']}&redirect_uri={cfg['redirect_uri']}&response_type=code&scope={' '.join(cfg['scopes'])}"

oauthTokenLink = 'https://id.twitch.tv/oauth2/token'

def get_Oauth_token(code):
    logger.warning(f"Got Oauth Code, getting access token...")
    response = requests.post(
        oauthTokenLink, 
        data={
            'client_id': cfg["client_id"],
            'client_secret': cfg["client_secret"],
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': cfg['redirect_uri'],
            }, 
        headers={'Accept': 'application/json'}
        )
    response.raise_for_status()
    r = response.json()
    authtoken = r['access_token']
    rauthtoken = r['refresh_token']
    logger.debug(f"Got Access Token:[{authtoken}] Refresh:[{rauthtoken}]")
    return {"token": authtoken}


class BaseBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
            
    async def event_ready(self):
        logger.warning(f'Bot logged in as [{self.nick}]')
        
    def oauth_token(self):
        return str(self._connection._token)

    async def event_message(self, m):
        if m.echo:
            logger.info(f"[Bot] [{m.channel.name}/{self.nick}] {m.content}")
        else:
            await self.handleChatMessage(m)
            await self.handle_commands(m)
        
    async def event_command_error(self, context: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.ArgumentParsingFailed):
            await context.send(error.message)
        elif isinstance(error, commands.MissingRequiredArgument):
            await context.send("You're missing an argument: " + error.name) 
        else:
            logger.error(f"[Bot] Command Error -> {error}")
            
    async def handleChatMessage(self, m):
        logger.info(f"[Bot] [{m.channel.name}/{m.author.name}] {m.content}")
     

    @commands.cooldown(rate=1, per=5, bucket=commands.Bucket.user)    
    @commands.command(name="help", aliases=["commands"])
    async def help_command(self, ctx: commands.Context):
        prefix = str(self._prefix).replace("'", "").replace("[", "").replace("]", "")
        commlist = str([k for k in self.commands.keys()]).replace("'", "").replace("[", "").replace("]", "")
        await ctx.reply(f"Prefix: {prefix} | Commands: {commlist}")


class DeezBot(BaseBot):
    def __init__(self, jnoun='butt', jemote='Kappa', jpath='db/jokes.json', 
            jdelay=[2,5], igpath='db/ignore.json', *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.jnoun = jnoun
        self.jemote = jemote
        self.jpath = jpath
        self.jdelay = jdelay
        self.igpath = igpath
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)
        self.jokes = loadJSON(self.jpath)
        self.ignoreList = set(loadJSON(self.igpath))

    async def event_ready(self):
        logger.warning(f'Bot logged in as [{self.nick}]')
        await self.join_channels([self.nick])
        
    async def handleChatMessage(self, m):
        logger.info(f"[Bot] [{m.channel.name}/{m.author.name}] {m.content}")
        await self.makeJoke(m)
    
    def resetjcount(self):
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)
    
    async def makeJoke(self, m):
        for p in self._prefix: # ignore commands
            if m.content.startswith(p):
                return
        if m.author.name not in self.ignoreList:
            # check for joke keyword
            for key in self.jokes:
                if key in m.content.lower():
                    await m.channel.send(f"{self.jokes[key]}! {self.jemote}")
                    self.resetjcount()
                    return 
            # make random joke
            self.jcount += 1
            if self.jcount >= self.jcountmax:
                r = replace_random_noun_chunk(m.content, self.jnoun)
                if r:
                    self.resetjcount()
                    await m.channel.send(f"{r}")


    @commands.cooldown(rate=1, per=5, bucket=commands.Bucket.user) 
    @commands.command(name="ignore", aliases=["stop", "ignoreme"])
    async def ignore_command(self, ctx: commands.Context):
        self.ignoreList.add(ctx.author.name)
        saveJSON(list(self.ignoreList), self.igpath)
        await ctx.reply(f"@{ctx.author.name}, I will ignore you.")


    @commands.cooldown(rate=1, per=5, bucket=commands.Bucket.user) 
    @commands.command(name="unignore", aliases=["unignoreme", "listen"])
    async def unignore_command(self, ctx: commands.Context):
        self.ignoreList.discard(ctx.author.name)
        saveJSON(list(self.ignoreList), self.igpath)
        await ctx.reply(f"@{ctx.author.name}, I am no longer ignoring you.")