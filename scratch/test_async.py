
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
import uuid

import pandas as pd
import numpy as np

import threading
import aiofiles
import asyncio
from dataclasses import dataclass
from tastytrade import DXLinkStreamer
from tastytrade.instruments import get_option_chain
from tastytrade.dxfeed import Greeks, Quote, Candle, Summary, Trade
from tastytrade.instruments import Equity, Option, OptionType
from tastytrade.session import Session
from tastytrade.dxfeed import EventType
from tastytrade import today_in_new_york, now_in_new_york

shared_dir = os.environ.get("SHARED_DIR")

def is_test_func():
    return False if os.environ.get('IS_TEST') == 'FALSE' else True

def get_session(remember_me=True):
    
    is_test = is_test_func()
    username = os.environ.get('TASTYTRADE_USERNAME')
    
    daystamp = now_in_new_york().strftime("%Y-%m-%d")
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


async def save_data_to_json(ticker,streamer_symbols,event_type,event):
    print("here1111111111111111111111111111111111")
    tstamp = now_in_new_york().strftime("%Y-%m-%d-%H-%M-%S.%f")
    daystamp = now_in_new_york().strftime("%Y-%m-%d")
    workdir = os.path.join(shared_dir,ticker,daystamp,streamer_symbols,event_type)
    print(f"{tstamp} {workdir}")
    await aiofiles.os.makedirs(workdir,exists_ok=True)
    print(f"mkdir done")
    uid = uuid.uuid4().hex
    json_file = os.path.join(workdir,f'{tstamp}-uid-{uid}.json')
    async with aiofiles.open(json_file,'w') as f:
        event_dict = dict(event)
        await f.write(json.dumps(event_dict,indent=4,sort_keys=True,default=str))
    print("here2222222222222222222222222")


#
# below are copy pastas authored by Graeme22
# amazing stuff!!!
# https://tastyworks-api.readthedocs.io/en/latest/data-streamer.html#advanced-usage
# commit https://github.com/tastyware/tastytrade/blob/97e1bc6632cfd4a15721da816085eb906a02bcb0/docs/data-streamer.rst#L76
#
CANDLE_TYPE = '15s'
@dataclass
class LivePrices:
    quotes: dict[str, Quote]
    greeks: dict[str, Summary]
    candles: dict[str, Candle]
    summaries: dict[str, Summary]
    trades: dict[str, Trade]
    streamer: DXLinkStreamer
    underlying: list[Equity]
    puts: list[Option]
    calls: list[Option]
    streamer_symbols: list[str]
    ticker: str
    @classmethod
    async def create(
        cls,
        session: Session,
        ticker: str = 'SPY',
        expiration: datetime.date = today_in_new_york()
        ):

        underlying = Equity.get_equity(session, ticker)
        chain = get_option_chain(session, ticker)
        options = [o for o in chain[expiration]]
        # the `streamer_symbol` property is the symbol used by the streamer
        streamer_symbols = [o.streamer_symbol for o in options]

        streamer = await DXLinkStreamer.create(session)

        # subscribe to quotes and greeks for all options on that date
        await streamer.subscribe(EventType.QUOTE, [ticker] + streamer_symbols)
        await streamer.subscribe(EventType.SUMMARY, streamer_symbols)
        await streamer.subscribe(EventType.TRADE, streamer_symbols)
        await streamer.subscribe(EventType.GREEKS, streamer_symbols)
        #start_time = datetime.datetime(2024,9,25,7,0,0)
        start_time = now_in_new_york()
        # interval '15s', '5m', '1h', '3d',
        await streamer.subscribe_candle([ticker] + streamer_symbols, CANDLE_TYPE, start_time)

        puts = [o for o in options if o.option_type == OptionType.PUT]
        calls = [o for o in options if o.option_type == OptionType.CALL]

        self = cls({}, {}, {}, {}, {}, streamer, 
            underlying, puts, calls, streamer_symbols,ticker)

        t_listen_quotes = asyncio.create_task(self._update_quotes())
        t_listen_summaries = asyncio.create_task(self._update_summaries())
        t_listen_trades = asyncio.create_task(self._update_trades())
        t_listen_greeks = asyncio.create_task(self._update_greeks())
        t_listen_candles = asyncio.create_task(self._update_candles())
        
        asyncio.gather(t_listen_quotes, t_listen_candles, t_listen_summaries, t_listen_trades, t_listen_greeks)

        # wait we have quotes and greeks for each option
        while len(self.quotes) < 1 or len(self.greeks) < 1:
            await asyncio.sleep(0.1)

        return self

    async def shutdown(self):
        logger.debug(f"sreamer.unsubscribe...{self.streamer_symbols}")
        await self.streamer.unsubscribe(EventType.QUOTE, self.streamer_symbols)
        await self.streamer.unsubscribe(EventType.SUMMARY, self.streamer_symbols)
        await self.streamer.unsubscribe(EventType.TRADE, self.streamer_symbols)
        await self.streamer.unsubscribe_candle([ticker] + +self.streamer_symbols,CANDLE_TYPE)
        await self.streamer.close()
        logger.debug(f"sreamer closed...{self.streamer_symbols}")

    async def _update_quotes(self):
        async for e in self.streamer.listen(EventType.QUOTE):
            #logger.debug(str(e))
            self.quotes[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.QUOTE,e)

    async def _update_candles(self):
        async for e in self.streamer.listen(EventType.CANDLE):
            #logger.debug(str(e))
            streamer_symbols = e.eventSymbol.replace("{=15s,tho=true}","")
            print("here000000000000000000000000000000CANDLE")
            self.candles[streamer_symbols] = e
            await save_data_to_json(self.ticker,streamer_symbols,EventType.CANDLE,e)

    async def _update_summaries(self):
        async for e in self.streamer.listen(EventType.SUMMARY):
            #logger.debug(str(e))
            print("here000000000000000000000000000000SUMMARY")
            self.summaries[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.SUMMARY,e)

    async def _update_trades(self):
        async for e in self.streamer.listen(EventType.TRADE):
            #logger.debug(str(e))
            print("here000000000000000000000000000000TRADE")
            self.trades[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.TRADE,e)

    async def _update_greeks(self):
        async for e in self.streamer.listen(EventType.GREEKS):
            #logger.debug(str(e))
            print("here000000000000000000000000000000GREEKS")
            self.trades[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.GREEKS,e)

def get_cancel_file(ticker):
    return f"/tmp/cancel-{ticker}.txt"

def get_running_file(ticker):
    return f"/tmp/running-{ticker}.txt"

async def background_subscribe(ticker,session):
    running_file = get_running_file(ticker)
    cancel_file = get_cancel_file(ticker)
    if not os.path.exists(running_file):
        pathlib.Path(running_file).touch()
    live_prices = await LivePrices.create(session,ticker)
    try:
        while True:
            # Print or process the quotes in real time
            logger.info(f"Current quotes: {live_prices.quotes}")
            logger.info(f"Current candles: {live_prices.candles}")
            logger.info(f"Current summaries: {live_prices.summaries}")
            logger.info(f"Current trades {live_prices.trades}")
            logger.info(f"Current greeks {live_prices.greeks}")
            await asyncio.sleep(5)
            pathlib.Path(running_file).touch()
            if os.path.exists(cancel_file):
                logger.info(f"canceljob receieved...")
                os.remove(cancel_file)
                logger.info(f"canceling!")
                await live_prices.shutdown()
                if os.path.exists(running_file):
                    os.remove(running_file)
                raise ValueError("canceljob")
    except KeyboardInterrupt:
        logger.error("Stopping live price streaming...")
    finally:
        if os.path.exists(running_file):
            os.remove(running_file)

def runshit(ticker,session):
    asyncio.run(background_subscribe(ticker,session))

def loop_in_thread(loop,ticker,session):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(background_subscribe(ticker,session))

if __name__ == "__main__":
    logging.basicConfig(
        filename='mylog.txt',
        level=logging.INFO, # level=logging.DEBUG, # 
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    logging.basicConfig(level=logging.INFO)
    ticker = sys.argv[1]
    session = get_session()
    if True:
        runshit(ticker,session)
    if False:
        loop = asyncio.get_event_loop()
        t = threading.Thread(target=loop_in_thread, args=(loop,ticker,session))
        t.start()
        print("done")
        time.sleep(10)
        print("done")


"""

cd ..

#docker run -it -u $(id -u):$(id -g) -p 80:80 \
docker run -it -p 80:80 \
    --env-file .env -e SHARED_DIR=/shared \
    -v ghetto-gex-live_shared:/shared \
    -v $PWD:/opt/app \
    -w /opt/app pangyuteng/ghetto-gex-live:latest bash

    
"""