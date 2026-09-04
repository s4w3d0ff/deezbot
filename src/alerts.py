import logging
from poolguy import Alert

logger = logging.getLogger(__name__)


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
