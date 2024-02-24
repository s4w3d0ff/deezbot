import webbrowser
from quart import redirect, request, Quart

from deezbot import logging, asyncio, parse_url, cfg
from deezbot import DeezBot, oauthLink, get_Oauth_token

app = Quart("Deeznutzbot")

bot = None
login_info = None
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s-%(levelname)s-[%(name)s] %(message)s", 
    datefmt="%I:%M:%S%p"
)

closeBrowser = """
<!DOCTYPE html>
<html lang="en">
<head>
	<script>
		function closeWindow() {
			window.close();
		};
	</script>
</head>
<body>
	<button id="closeButton" onclick="closeWindow()">Close Window</button>
	<script>
		document.getElementById("closeButton").click();
	</script>
</body>
</html>
"""

@app.route('/')
async def index():
	global bot
	if not login_info:
		logger.warning(f"Redirecting for Oauth...")
		return redirect(oauthLink)
	if not bot:
		logger.warning(f"Starting bot...")
		ploop = asyncio.get_running_loop()
		bot = DeezBot(
			client_secret=cfg["client_secret"],
			loop=ploop, 
			**login_info, 
			**cfg['bot']
		)
		asyncio.create_task(bot.start())
	return closeBrowser

rurl = parse_url(cfg["redirect_uri"])

@app.route(f"/{rurl['route']}")
async def callback():
	global login_info
	code = request.args.get('code')
	login_info = get_Oauth_token(code)
	return redirect('/')

webbrowser.open(f"{rurl['scheme']}://{rurl['host']}:{rurl['port']}/")

if __name__ == '__main__':
	app.run(host=rurl['host'], port=rurl['port'], debug=False)