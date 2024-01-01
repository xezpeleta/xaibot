#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

import os
import re
import logging
import trafilatura
from telegram import Update, MessageEntity
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from functools import wraps
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv
# Load envars from .env file
load_dotenv()

# Get envars
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_NAME = os.getenv("TELEGRAM_BOT_NAME")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")
TELEGRAM_ALLOWED_USERS = [int(user_id) for user_id in os.getenv("TELEGRAM_ALLOWED_USERS").split(",")]
TELEGRAM_ALLOWED_GROUPS = [int(group_id) for group_id in os.getenv("TELEGRAM_ALLOWED_GROUPS").split(",")]
MISTRALAI_API_KEY = os.getenv("MISTRALAI_API_KEY")
FORWARD_PROXY_URL = os.getenv("FORWARD_PROXY_URL")

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
/help - Show this help message\n
/getid - Get user id and chat id (use this ids if you want access to the bot) \n
/chat - Chat with the Mistral LLM\n
/link - Send link content to Mistral LLM\n
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    username = update.effective_user.username
    logger.warning("[INFO] Help command received from user %s" % (username))
    await update.message.reply_text(HELP)

def getTextFromLink(url):
    """Get link content"""
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-dev-shm-usage')
    logging.getLogger('selenium').setLevel(logging.DEBUG)
    with webdriver.Remote(command_executor="http://selenium:4444", options=options) as driver:
        try:
            # Test approach with trafilatura
            driver.get(FORWARD_PROXY_URL + url)
            html = driver.page_source
            logger.debug("[DEBUG] HTML: %s" % (html))
            #downloaded = trafilatura.fetch_url(FORWARD_PROXY_URL + url)
            downloaded = trafilatura.load_html(html)
            if downloaded is None:
                logger.warning("[WARNING] Error getting text from the link: %s" % (url))
                raise Exception("Error getting text from the link: %s" % (url))
            text = trafilatura.extract(downloaded, output_format='json', with_metadata=True, include_comments=False, url=url)
            # Remove empty lines
            text = os.linesep.join([s for s in text.splitlines() if s])
            logger.info("[INFO] Get text from the link: %s  (Total: %s characters)" % (url, len(text)))
            # TODO: limit text to 2000 characters?
            # TODO: avoid prompt injection
        except:
            logger.warning("[WARNING] Error getting text from the link: %s" % (url))
            raise Exception("Error getting text from the link: %s" % (url))
        finally:
            driver.close()
    return text

@restricted
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply using Mistral AI"""
    username = update.effective_user.username
    message = update.message
    answer = ""
    history = ""

    # This is a workaround to avoid undersired replies from the bot
    # If the chat is a group (or supergroup) and the message is a reply for someone else (not for for the bot)
    # or it ignore it
    if message.entities and message.entities[0].type != MessageEntity.BOT_COMMAND:
        if message.reply_to_message and message.reply_to_message.from_user.username != TELEGRAM_BOT_USERNAME:
            if '@' + TELEGRAM_BOT_USERNAME not in message.text and message.chat.type != 'private':
                logger.debug("[DEBUG] Message is a reply for someone else (not for the bot). Ignoring it.")
                return

    logger.info("[INFO] Chat message received from user %s : %s" % (username, message.text))

    # If the message is a link, get the link content
    text = ""
    entities = update.message.parse_entities(types=MessageEntity.URL)
    if not entities:
        logger.debug("[DEBUG] No links in the message. Checking reply message.")
        if update.message.reply_to_message:
            message = update.message.reply_to_message
            history = update.message.reply_to_message.text
            entities = message.parse_entities(types=MessageEntity.URL)
    
    for entity in entities:
        link = message.parse_entity(entity)
        logger.info("[INFO] Link received from user %s: %s." % (username, link))
        try:
            text = getTextFromLink(link)
            # Include the link in the answer message
            answer = link + " "
        except:
            # muted by the moment
            #await update.message.reply_text("Sorry but I can't get the content: %s" % (link))
            return
    
    
    # If there is just a link, no question from the user, ask for a summary
    message = update.message.text
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
            ChatMessage(role="assistant", content=history or ""),
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
        await update.message.reply_text(answer_escaped, disable_web_page_preview=True, parse_mode="MarkdownV2")
    except:
        await update.message.reply_text(answer, disable_web_page_preview=True)

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get user and chat id"""
    user = update.effective_user.id
    chat = update.effective_chat.id
    logger.info("[INFO] Get ID command received from user %s and chat %s " % (user, chat))
    await update.message.reply_text("User ID: `" + str(user) + "`\nChat ID: `" + str(chat) + "`\n", parse_mode="MarkdownV2")

async def nitter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    '''Substitute Twitter links with Nitter'''
    username = update.effective_user.username
    message = update.message
    logger.info("[INFO] Twitter command received from user %s : %s" % (username, message.text))

    # Get the links from the message
    entities = message.parse_entities(types=MessageEntity.URL)
    # If no links in the message, get the links from the reply message
    if not entities:
        logger.debug("[DEBUG] No links in the message. Checking reply message.")
        message = update.message.reply_to_message
        entities = message.parse_entities(types=MessageEntity.URL)
    else:
        logger.debug("[DEBUG] Entities: %s" % (entities))
    
    for entity in entities:
        link = message.parse_entity(entity)
        logger.info("[INFO] Link received from user %s: %s." % (username, link))
        # Substitute Twitter links with Nitter
        if "twitter.com" or "x.com" in link:
            nitter_link = link.replace("https://twitter.com", "https://nitter.net").replace("https://x.com", "https://nitter.net")
            logger.info("[INFO] Nitter link: %s." % (nitter_link))
            await update.message.reply_text(nitter_link, disable_web_page_preview=True)

def main() -> None:
    logger.info("Starting bot...")

    # Get Telegram Bot Token from envar
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(telegram_bot_token).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("getid", getid))
    application.add_handler(CommandHandler("chat", chat))
    application.add_handler(CommandHandler("link", chat))
    application.add_handler(CommandHandler("nitter", nitter))

    # DISABLED - Get any link from the groups (no mention non reply needed)
    #application.add_handler(MessageHandler(filters.Entity("url") | filters.Entity("text_link"), nitter))

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
