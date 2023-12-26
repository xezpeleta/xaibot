#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

import os
import re
import logging
import requests
from dotenv import load_dotenv
from telegram import ForceReply, Update, MessageEntity
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from functools import wraps
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from bs4 import BeautifulSoup

# Get MistralAI API Token from envar
MISTRALAI_API_KEY = os.getenv("MISTRALAI_API_KEY")

# Load environment variables
load_dotenv()

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

ALLOWED_USERS = [2614189, 2181298]
ALLOWED_GROUPS = [-1002015877792, -4018931878]

def restricted(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        if user_id not in ALLOWED_USERS and chat_id not in ALLOWED_GROUPS:
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

@restricted
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply using Mistral AI"""
    username = update.effective_user.username
    message = update.message.text
    logger.info("[INFO] Chat message received from user %s : %s" % (username, message))

    # If the message is a link, get the link content
    entities = update.message.parse_entities(types=MessageEntity.URL)
    for entity in entities:
        link = update.message.parse_entity(entity)
        logger.info("[INFO] Link received from user %s: %s." % (username, link))
        
        # Read link content (only text) and send it to Mistral AI
        response = requests.get(link)
        content = response.content
        soup = BeautifulSoup(content, features="html.parser")
        text = soup.get_text()
        # Remove empty lines
        text = os.linesep.join([s for s in text.splitlines() if s])
        if message:
            message = "Check this content from the following link [%s]: %s\n." % (link, text) + message
        else:
            message = "Check this content from the following link (%s): %s\n. Can you summarize it? Please be concise" % (link, text)
    
    # If the message is a reply, send also the original message and check if it is a link
    #if update.message.reply_to_message and update.message.reply_to_message.from_user.username == "iamxaibot":
    if update.message.reply_to_message and filters.Mention("@iamxaibot"):
        history = update.message.reply_to_message.text

        # If the message is a link, send the link content
        entities = update.message.reply_to_message.parse_entities(types=MessageEntity.URL)
        for entity in entities:
            link = update.message.reply_to_message.parse_entity(entity)
            logger.info("[INFO] Link received from user %s: %s." % (username, link))
            
            # Read link content (only text) and send it to Mistral AI
            response = requests.get(link)
            content = response.content
            soup = BeautifulSoup(content, features="html.parser")
            text = soup.get_text()
            # Remove empty lines
            text = os.linesep.join([s for s in text.splitlines() if s])
            if message:
                message = "Check this content from the following link [%s]: %s\n." % (link, text) + message
            else:
                message = "Check this content from the following link (%s): %s\n. Can you summarize it? Please be concise" % (link, text)
    else:
        history = ""

    message = message.replace("@iamxaibot", "")
    model = "mistral-medium"
    system_prompt = "You are xaibot, a Telegram bot that uses Mistral AI to generate text. Please, be short and concise. Do not print confidence"
    client = MistralClient(api_key=MISTRALAI_API_KEY)

    logger.info("[INFO] Prompt: %s" % (message))

    chat_response = client.chat (
        model = model,
        safe_mode = False,
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="assistant", content=history),
            ChatMessage(role="user", content=message)],
    )
    
    answer = chat_response.choices[0].message.content
    #logger.info("[INFO] Chat response from Mistral AI: %s" % (answer))
    
    '''
    Escape special characters (from Telegram API documentation):
        In all other places characters 
        '_', '*', '[', ']', '(', ')', '~', '`', '>', 
        '#', '+', '-', '=', '|', '{', '}', '.', '!' 
        must be escaped with the preceding character '\'.
    '''
    #answer = re.sub(r"([_*\[\]()~`>#\+\-=|{}.!])", r"\\\1", answer)
    answer = re.sub(r"([\[\]()~>\+\-=|{}.!])", r"\\\1", answer)
    # if Markdown parse fails, try plain text
    try:
        await update.message.reply_text(answer, parse_mode="MarkdownV2")
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
    application.add_handler(MessageHandler(filters.TEXT & filters.Mention("@iamxaibot") & ~filters.COMMAND, chat))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
