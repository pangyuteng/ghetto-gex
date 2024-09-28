
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
        listen: bool = True,
        ):

        underlying = Equity.get_equity(session, symbol)
        streamer_symbols = [underlying.streamer_symbol]
        
        streamer = await DXLinkStreamer.create(session)

        # subscribe to quotes and greeks for all options on that date
        await streamer.subscribe(EventType.QUOTE, streamer_symbols)
        await streamer.subscribe(EventType.CANDLE, streamer_symbols)
        await streamer.subscribe(EventType.SUMMARY, streamer_symbols)
        await streamer.subscribe(EventType.TRADE, streamer_symbols)

        self = cls({}, {}, {}, {}, streamer, underlying)

        t_listen_quotes = asyncio.create_task(self._update_quotes())
        t_listen_candles = asyncio.create_task(self._update_candles())
        t_listen_summaries = asyncio.create_task(self._update_summaries())
        t_listen_trades = asyncio.create_task(self._update_trades())
        
        if listen:
            await asyncio.gather(t_listen_quotes, t_listen_candles,t_listen_summaries,t_listen_trades)
        else:
            asyncio.gather(t_listen_quotes, t_listen_candles,t_listen_summaries,t_listen_trades)
            # wait we have quotes and greeks for each option
            while len(self.quotes) != 1 or len(self.candles) != 1 \
                or len(self.summaries) !=1 or len(self.trades) != 1:
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


async def asyncmain(ticker,session):
    live_prices = await UnderlyingLivePrices.create(session,ticker)
    try:
        while True:
            # Print or process the quotes in real time
            print("Current quotes:", live_prices.quotes)
            print("Current candles:", live_prices.candles)
            print("Current summaries:", live_prices.summaries)
            print("Current trades:", live_prices.trades)
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping live price streaming...")

def main(ticker,session):
    output = asyncio.run(UnderlyingLivePrices.create(session,ticker))

if __name__ == "__main__":
    logging.basicConfig(
        filename='mylog.txt',
        level=logging.DEBUG,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    
    ticker = sys.argv[1]
    session = get_session()
    asyncio.run(asyncmain(ticker,session))
