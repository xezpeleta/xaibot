#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

import os
import re
import logging
import trafilatura
from telegram import ForceReply, Update, MessageEntity
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from functools import wraps
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage

# Get envars
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_NAME = os.getenv("TELEGRAM_BOT_NAME")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")
TELEGRAM_ALLOWED_USERS = [int(user_id) for user_id in os.getenv("TELEGRAM_ALLOWED_USERS").split(",")]
TELEGRAM_ALLOWED_GROUPS = [int(group_id) for group_id in os.getenv("TELEGRAM_ALLOWED_GROUPS").split(",")]
MISTRALAI_API_KEY = os.getenv("MISTRALAI_API_KEY")

# Enable logging
loglevel = os.getenv("LOGLEVEL", "INFO")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=loglevel
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(loglevel)

HELP = """
/start - Start the bot\n
/help - Show this help message\n
/getid - Get user and chat id\n
/chat - Chat with the bot\n
/link - [TODO] Send link\n
/img - [TODO] Send image\n
"""

def restricted(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        if user_id not in TELEGRAM_ALLOWED_USERS and chat_id not in TELEGRAM_ALLOWED_GROUPS:
            logger.warning("[WARNING] Unauthorized access denied for user %s or group %s." % (user_id, chat_id))
            print(f"Unauthorized access denied for user {user_id} or group {chat_id}.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    logger.warning("[INFO] Start command received from user %s" % (user.username))
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    username = update.effective_user.username
    logger.warning("[INFO] Help command received from user %s" % (username))
    await update.message.reply_text(HELP)

def getTextFromLink(url):
    """Get link content"""
    try:
        # Test approach with trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            logger.warning("[WARNING] Error getting text from the link: %s" % (url))
            raise Exception("Error getting text from the link: %s" % (url))
        text = trafilatura.extract(downloaded, output_format='json', with_metadata=True, include_comments=False, url=url)
        # Remove empty lines
        text = os.linesep.join([s for s in text.splitlines() if s])
        logger.info("[INFO] Get text from the link: %s  (Total: %s characters)" % (url, len(text)))
        # TODO: limit text to 1000 characters?
        # TODO: avoid prompt injection
    except:
        logger.warning("[WARNING] Error getting text from the link: %s" % (url))
        raise Exception("Error getting text from the link: %s" % (url))
    return text

@restricted
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply using Mistral AI"""
    username = update.effective_user.username
    message = update.message.text
    answer = ""
    history = ""

    # This is a workaround to avoid undersired replies from the bot
    # If the chat is a group (or supergroup) and the message is a reply for someone else (not for for the bot)
    # or it ignore it
    if update.message.reply_to_message and update.message.reply_to_message.from_user.username != TELEGRAM_BOT_USERNAME:
        if '@' + TELEGRAM_BOT_USERNAME not in message:
            logger.debug("[DEBUG] Message is a reply for someone else (not for the bot). Ignoring it.")
            return

    logger.info("[INFO] Chat message received from user %s : %s" % (username, message))

    # If the message is a link, get the link content
    text = ""
    entities = update.message.parse_entities(types=MessageEntity.URL)
    for entity in entities:
        link = update.message.parse_entity(entity)
        logger.info("[INFO] Link received from user %s: %s." % (username, link))
        try:
            text = getTextFromLink(link)
            # Include the link in the answer message
            answer = link + " "
        except:
            # muted by the moment
            #await update.message.reply_text("Sorry but I can't get the content: %s" % (link))
            return

    if ( update.message.chat.type == 'private' and update.message.reply_to_message )\
        or ( ( update.message.chat.type != 'private' )\
        and ( update.message.reply_to_message and update.message.reply_to_message.from_user.username == TELEGRAM_BOT_USERNAME
        or "@" + TELEGRAM_BOT_USERNAME in message ) ):

        logger.debug("[DEBUG] Message is a reply for the bot.")
        history = update.message.reply_to_message.text

        # If the reply message contains a link, get the text from the link
        entities = update.message.reply_to_message.parse_entities(types=MessageEntity.URL)
        for entity in entities:
            link = update.message.reply_to_message.parse_entity(entity)
            logger.info("[INFO] Link received from user %s in a reply message: %s." % (username, link))
            
            # Read link content (only text) and send it to Mistral AI
            try:
                text = getTextFromLink(link)
                # Include the link in the answer message
                answer = link + " "
            except:
                # muted by the moment
                #await update.message.reply_text("Sorry but I can't get the content: %s" % (link))
                return
    
    # If there is no question from the user, only the link, ask for a summary
    if text != "":
        if message:
            message = "Check this content from the following link [%s]: %s\n." % (link, text) + message
        else:
            message = "Check this content from the following link (%s): %s\n. Can you summarize it? Please be concise" % (link, text)

    # Clean the prompt
    message = message.replace("@" + TELEGRAM_BOT_USERNAME, "")

    model = "mistral-medium"
    system_prompt = "You are %s, a Telegram bot that uses Mistral AI to generate text. Please, be short and concise. Do not print confidence" % (TELEGRAM_BOT_NAME)
    client = MistralClient(api_key=MISTRALAI_API_KEY)

    logger.debug("[DEBUG] History (assistant prompt): %s" % (history))
    logger.debug("[DEBUG] Message (user prompt): %s" % (message))

    chat_response = client.chat (
        model = model,
        safe_mode = False,
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="assistant", content=history),
            ChatMessage(role="user", content=message)],
    )
    
    answer = answer + chat_response.choices[0].message.content
    #logger.debug("[INFO] Chat response from Mistral AI: %s" % (answer))
    
    '''
    Escape special characters (from Telegram API documentation):
        In all other places characters 
        '_', '*', '[', ']', '(', ')', '~', '`', '>', 
        '#', '+', '-', '=', '|', '{', '}', '.', '!' 
        must be escaped with the preceding character '\'.
    '''
    #answer = re.sub(r"([_*\[\]()~`>#\+\-=|{}.!])", r"\\\1", answer)
    answer_escaped = re.sub(r"([\[\]()~>\+\-=|{}.!])", r"\\\1", answer)
    # if Markdown parse fails, try plain text
    try:
        await update.message.reply_text(answer_escaped, parse_mode="MarkdownV2")
    except:
        await update.message.reply_text(answer)

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get user and chat id"""
    user = update.effective_user.id
    chat = update.effective_chat.id
    logger.info("[INFO] Get ID command received from user %s and chat %s " % (user, chat))
    await update.message.reply_text("User ID: `" + str(user) + "`\nChat ID: `" + str(chat) + "`\n", parse_mode="MarkdownV2")

def main() -> None:
    logger.info("Starting bot...")

    # Get Telegram Bot Token from envar
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(telegram_bot_token).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("getid", getid))
    application.add_handler(CommandHandler("chat", chat))
    application.add_handler(CommandHandler("link", chat))

    # DISABLED - Get any link from the groups (no mention non reply needed)
    #application.add_handler(MessageHandler(filters.Entity("url") | filters.Entity("text_link"), chat))

    # Private messages: on non command i.e message, chat with Mistral AI
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, chat))

    # Groups: on non command i.e messages, if someone replies to the bot or mentions the bot
    # chat with Mistral AI
    application.add_handler(MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, chat))
    application.add_handler(MessageHandler(filters.TEXT & filters.Mention("@" + TELEGRAM_BOT_USERNAME) & ~filters.COMMAND, chat))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
