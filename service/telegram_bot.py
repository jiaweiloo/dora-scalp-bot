import logging
import time
from datetime import datetime
from typing import Set

from telegram import Update
from telegram.ext import *

from classes.singleton import Singleton
from custom_types.controller_type import EMode
from service.logging import telegram_bot_logger as logger
from settings import TELEGRAM_MODE
from utils.events import ee, TelegramEventType

API_KEY = '1945409432:AAFM9Mi-FWKYH4Zj1iNNqscK5nDVYS1Idfc'


class TelegramBot(metaclass=Singleton):
    dispatcher: Dispatcher
    updater: Updater
    chat_list: Set = set[469591760, 1746016549]
    starttime = datetime.now()

    def start_bot(self):
        date = datetime.now()
        logger.info(f'{date:%Y-%m-%d %H:%M:%S} > START TELEGRAM_BOT')
        self.updater = Updater(API_KEY, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # Commands
        self.dispatcher.add_handler(
            CommandHandler('start', self.start_command))
        self.dispatcher.add_handler(CommandHandler('help', self.help_command))
        self.dispatcher.add_handler(CommandHandler('test', self.test_command))
        self.dispatcher.add_handler(
            CommandHandler('stats', self.stats_command))
        self.dispatcher.add_handler(
            CommandHandler('custom', self.custom_command))

        # Messages
        self.dispatcher.add_handler(MessageHandler(
            Filters.text, self.handle_message))

        # Log all errors
        self.dispatcher.add_error_handler(self.error)

    def start_command(self, update, context):
        logger.info(update.message.chat.username)
        logger.info(update.message.chat.id)
        self.chat_list.add(update.message.chat.id)
        update.message.reply_text('Hello there! I\'m a bot. What\'s up?')

    def stats_command(self, update, context):
        text = str(update.message.text).lower()
        logger.info(f'User ({update.message.chat.id}) says: {text}')
        update.message.reply_text('CHECKING STATS...')
        ee.emit(TelegramEventType.STATS, update.message.chat.id)

    def help_command(self, update, context):
        logger.info(update.message)
        msg = (f"/help for help message\n"
               f"/stats for bot stats\n"
               f"/test to check telegram bot")
        update.message.reply_text(msg)

    def custom_command(self, update, context):
        update.message.reply_text(
            'This is a custom command, you can add whatever text you want here.')

    def test_command(self, update, context):
        text = str(update.message.text).lower()
        logger.info(f'User ({update.message.chat.id}) says: {text}')
        update.message.reply_text('Test successful...BOT RUNNING')

    def handle_message(self, update: Update, context: CallbackContext):
        text = str(update.message.text).lower()
        logger.info(f'User ({update.message.chat.id}) says: {text}')
        update.message.reply_text(update.message.text)

    def error(self, update, context):
        # Logs errors
        logger.error(f'Update {update} caused error {context.error}')

    def send_message(self, chat_id=-1001433775775, message="blank"):
        retry = 0
        while True and TELEGRAM_MODE == EMode.PRODUCTION and retry <= 3:
            try:
                self.dispatcher.bot.send_message(
                    chat_id=chat_id, text="<pre>" + message + "</pre>", parse_mode="HTML")
            except Exception as ex:
                print(f"TELEGRAM SEND FAILED: {retry}...\n"
                      f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break

    def run_bot(self):
        # Run the bot
        self.updater.start_polling()


telegram_bot = TelegramBot()

if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    logging.info("start TelegramBot.py")
    telegram_bot: TelegramBot = TelegramBot()
    telegram_bot.start_bot()
    msg = "🦺TEST TELEGRAM"
    telegram_bot.send_message(chat_id=469591760, message=msg)
    telegram_bot.send_message(chat_id=-1001433775775, message=msg)
    logging.info(msg)
