
import logging
logger = logging.getLogger(__file__)

import os
import re
import sys
import ast
import time
import math
import traceback
import datetime
import json
import pathlib

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

import threading
import asyncio
from dataclasses import dataclass
from tastytrade import DXLinkStreamer
from tastytrade.instruments import get_option_chain
from tastytrade.dxfeed import Greeks, Quote, Candle, Summary, Trade
from tastytrade.instruments import Equity, Option, OptionType
from tastytrade.utils import today_in_new_york
from tastytrade.session import Session
from tastytrade.dxfeed import EventType

def is_test_func():
    return False if os.environ.get('IS_TEST') == 'FALSE' else True

def get_session(remember_me=True):
    
    is_test = is_test_func()
    username = os.environ.get('TASTYTRADE_USERNAME')
    
    daystamp = datetime.datetime.now().strftime("%Y-%m-%d")
    token_file = f'/tmp/.tastytoken-{daystamp}.json'
    print(token_file)
    if not os.path.exists(token_file):
        password = os.environ.get('TASTYTRADE_PASSWORD')
        print(username,password)
        session = Session(username,password,remember_me=remember_me,is_test=is_test)
        # #use of remember_token locks the account!
        # TODO: need to read tasty api
        # with open(token_file,'w') as f:
        #    f.write(json.dumps({"remember_token":session.remember_token}))
        return session
    else:
        print('loading token file...')
        with open(token_file,'r') as f:
            content = json.loads(f.read())
            remember_token = content["remember_token"]
            print("remember_token",remember_token)
            return Session(username,remember_token=remember_token,is_test=is_test)

#
# below are copy pastas authored by Graeme22
# amazing stuff!!!
# https://tastyworks-api.readthedocs.io/en/latest/data-streamer.html#advanced-usage
# commit https://github.com/tastyware/tastytrade/blob/97e1bc6632cfd4a15721da816085eb906a02bcb0/docs/data-streamer.rst#L76
#
@dataclass
class UnderlyingLivePrices:
    quotes: dict[str, Quote]
    candles: dict[str, Candle]
    summaries: dict[str, Summary]
    trades: dict[str, Trade]
    streamer: DXLinkStreamer
    underlying: list[Equity]

    @classmethod
    async def create(
        cls,
        session: Session,
        symbol: str = 'SPY',
        ):

        underlying = Equity.get_equity(session, symbol)
        streamer_symbols = [underlying.streamer_symbol]
        
        streamer = await DXLinkStreamer.create(session)

        # subscribe to quotes and greeks for all options on that date
        await streamer.subscribe(EventType.QUOTE, streamer_symbols)
        await streamer.subscribe(EventType.CANDLE, streamer_symbols)
        start_date = datetime.datetime(2024,9,25,7,0,0)
        # interval '15s', '5m', '1h', '3d',
        await streamer.subscribe_candle(streamer_symbols, '15s', start_date)
        await streamer.subscribe(EventType.SUMMARY, streamer_symbols)
        await streamer.subscribe(EventType.TRADE, streamer_symbols)

        self = cls({}, {}, {}, {}, streamer, underlying)

        t_listen_quotes = asyncio.create_task(self._update_quotes())
        t_listen_candles = asyncio.create_task(self._update_candles())
        t_listen_summaries = asyncio.create_task(self._update_summaries())
        t_listen_trades = asyncio.create_task(self._update_trades())
        
        asyncio.gather(t_listen_quotes, t_listen_candles,t_listen_summaries,t_listen_trades)

        # wait we have quotes and greeks for each option
        #while len(self.quotes) != 1 or len(self.candles) != 1 \
        #    or len(self.summaries) !=1 or len(self.trades) != 1:
        while len(self.quotes) != 1:
            await asyncio.sleep(0.1)

        return self


    async def _update_quotes(self):
        async for e in self.streamer.listen(EventType.QUOTE):
            logger.debug(str(e))
            self.quotes[e.eventSymbol] = e

    async def _update_candles(self):
        async for e in self.streamer.listen(EventType.CANDLE):
            logger.debug(str(e))
            self.candles[e.eventSymbol] = e

    async def _update_summaries(self):
        async for e in self.streamer.listen(EventType.SUMMARY):
            logger.debug(str(e))
            self.summaries[e.eventSymbol] = e

    async def _update_trades(self):
        async for e in self.streamer.listen(EventType.TRADE):
            logger.debug(str(e))
            self.trades[e.eventSymbol] = e

def get_cancel_file(ticker):
    return f"/tmp/cancel-{ticker}.txt"
def get_running_file(ticker):
    return f"/tmp/runninng-{ticker}.txt"

async def background_subscribe(ticker):
    running_file = get_running_file(ticker)
    cancel_file = get_cancel_file(ticker)
    if not os.path.exists(running_file):
        pathlib.Path(running_file).touch()
    session = get_session()
    live_prices = await UnderlyingLivePrices.create(session,ticker)
    try:
        while True:
            # Print or process the quotes in real time
            logger.info(f"Current quotes: {live_prices.quotes}")
            logger.info(f"Current candles: {live_prices.candles}")
            logger.info(f"Current summaries: {live_prices.summaries}")
            logger.info(f"Current trades {live_prices.trades}")
            print(dir(live_prices))
            await asyncio.sleep(10)
            if os.path.exists(cancel_file):
                logger.info(f"canceljob receieved...")
                os.remove(cancel_file)
                logger.info(f"canceling!")
                if os.path.exists(running_file):
                    os.remove(running_file)
                raise ValueError("canceljob")
    except KeyboardInterrupt:
        logger.error("Stopping live price streaming...")
    finally:
        if os.path.exists(running_file):
            os.remove(running_file)

def runshit(ticker):
    asyncio.run(background_subscribe(ticker))

def loop_in_thread(loop,ticker):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(background_subscribe(ticker))

if __name__ == "__main__":
    logging.basicConfig(
        filename='mylog.txt',
        level=logging.INFO,#level=logging.DEBUG,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    
    ticker = sys.argv[1]

    if False:
        runshit(ticker)
    if False:
        loop = asyncio.get_event_loop()
        t = threading.Thread(target=loop_in_thread, args=(loop,ticker))
        t.start()
        print("done")
        time.sleep(10)
        print("done")


"""

cd ..

docker run -it -u $(id -u):$(id -g) -p 80:80 \
    --env-file .env \
    -v ghetto-gex-live_shared:/shared \
    -v $PWD:/opt/app \
    -w /opt/app pangyuteng/ghetto-gex-live:latest bash

    
"""