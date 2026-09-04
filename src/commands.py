import logging
from poolguy import rate_limit, command

logger = logging.getLogger(__name__)


class CommandsMixin:
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
                logger.info(f'Changed {user["username"]} emote: {emote}')
            except:
                logger.exception(f"\n")

    @command(name="join")
    @rate_limit(calls=1, period=15)
    async def cmd_join(self, user, channel, args):
        """ Adds the user calling the command to the channel list """
        if self._is_own_channel(user, channel):
            try:
                await self._update_channel_list(user["user_id"], config={
                        "jemote": self.default_jemote
                    })
                await self.send_chat(
                        f":3 @{user['username']}",
                        channel["broadcaster_id"]
                    )
                logger.info(f'Joining channel: {user["user_id"]}({user["username"]})')
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
                logger.info(f'Leaving channel: {user["user_id"]}({user["username"]})')
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
            logger.info(f'Added {user["user_id"]}({user["username"]}) to ignore list')
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
            logger.info(f"Removed {user['user_id']}({user['username']}) from ignore list")
        except:
            logger.exception(f"\n")
