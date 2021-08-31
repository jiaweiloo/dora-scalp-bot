import asyncio
import logging
from concurrent.futures.thread import ThreadPoolExecutor

import uvicorn
from fastapi import FastAPI

from api.settings_controller import settings
from custom_types.controller_type import EMode
from main_controller import Controller
from service.logging import setup_logging, controller_logger as logger
from settings import MODE
from service.telegram_bot import telegram_bot
from utils.events import TelegramEventType, ee

app = FastAPI()

app.include_router(settings, prefix='/api/v1/settings', tags=['settings'])


async def main():
    setup_logging()
    logger.info("start controller")

    telegram_bot.start_bot()
    controller = Controller()
    if MODE == EMode.PRODUCTION:
        with ThreadPoolExecutor(max_workers=1) as executor:
            event_loop = asyncio.get_event_loop()
            await asyncio.gather(controller.run_signal_bot(),
                                 # event_loop.run_in_executor(executor, telegram_bot.run_bot)
                                 )
    elif MODE == EMode.TEST:
        controller.read_filepath_or_buffer()


@app.on_event('startup')
async def app_startup():
    asyncio.create_task(main())


@app.get('/stats')
async def app_startup():
    ee.emit(TelegramEventType.STATS, -1001433775775)
    logger.info(f"emitting TelegramEventType.STATS")


if __name__ == '__main__':
    uvicorn.run(app)
