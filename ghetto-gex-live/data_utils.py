
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

shared_dir = os.environ.get("SHARED_DIR")

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
        expiration: datetime.date = today_in_new_york()
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
        asyncio.gather(t_listen_quotes, t_listen_candles,t_listen_summaries,t_listen_trades)

        # wait we have quotes and greeks for each option
        while len(self.quotes) != 1 or len(self.candles) != 1 \
            or len(self.summaries) !=1 or len(self.trades) != 1:
            await asyncio.sleep(0.1)

        return self

    async def _update_quotes(self):
        async for e in self.streamer.listen(EventType.QUOTE):
            self.quotes[e.eventSymbol] = e

    async def _update_candles(self):
        async for e in self.streamer.listen(EventType.CANDLE):
            self.candles[e.eventSymbol] = e

    async def _update_summaries(self):
        async for e in self.streamer.listen(EventType.SUMMARY):
            self.summaries[e.eventSymbol] = e

    async def _update_trades(self):
        async for e in self.streamer.listen(EventType.TRADE):
            self.trades[e.eventSymbol] = e

@dataclass
class OptionsLivePrices:
    quotes: dict[str, Quote]
    greeks: dict[str, Greeks]
    candles: dict[str, Candle]
    summaries: dict[str, Summary]
    trades: dict[str, Trade]
    streamer: DXLinkStreamer
    puts: list[Option]
    calls: list[Option]

    @classmethod
    async def create(
        cls,
        session: Session,
        symbol: str = 'SPY',
        expiration: datetime.date = today_in_new_york()
        ):

        chain = get_option_chain(session, symbol)
        options = [o for o in chain[expiration]]
        # the `streamer_symbol` property is the symbol used by the streamer
        streamer_symbols = [o.streamer_symbol for o in options]
        
        streamer = await DXLinkStreamer.create(session)
        # subscribe to quotes and greeks for all options on that date
        await streamer.subscribe(EventType.QUOTE, [symbol] + streamer_symbols)
        await streamer.subscribe(EventType.CANDLE, [symbol] + streamer_symbols)
        await streamer.subscribe(EventType.GREEKS, streamer_symbols)
        await streamer.subscribe(EventType.SUMMARY, streamer_symbols)
        await streamer.subscribe(EventType.TRADE, streamer_symbols)

        puts = [o for o in options if o.option_type == OptionType.PUT]
        calls = [o for o in options if o.option_type == OptionType.CALL]

        self = cls({}, {}, {}, {}, {}, streamer, puts, calls)

        t_listen_greeks = asyncio.create_task(self._update_greeks())
        t_listen_quotes = asyncio.create_task(self._update_quotes())
        t_listen_candles = asyncio.create_task(self._update_candles())
        t_listen_summaries = asyncio.create_task(self._update_summaries())
        t_listen_trades = asyncio.create_task(self._update_trades())
        asyncio.gather(t_listen_greeks, t_listen_quotes, t_listen_candles,t_listen_summaries,t_listen_trades)

        # wait we have quotes and greeks for each option

        data_len_limit = len(options)*0.5 # let's accep at 50% of available data.
        while len(self.greeks) <  data_len_limit \
            or len(self.quotes) < data_len_limit \
            or len(self.candles) < data_len_limit \
            or len(self.summaries) < data_len_limit \
            or len(self.trades) < data_len_limit:
            print(len(options),len(self.greeks),len(self.quotes),len(self.candles),len(self.summaries),len(self.trades))
            await asyncio.sleep(1)
            
        return self

    async def _update_greeks(self):
        async for e in self.streamer.listen(EventType.GREEKS):
            logger.debug('greeks',e)
            self.greeks[e.eventSymbol] = e

    async def _update_quotes(self):
        async for e in self.streamer.listen(EventType.QUOTE):
            logger.debug('quotes',e)
            self.quotes[e.eventSymbol] = e

    async def _update_candles(self):
        async for e in self.streamer.listen(EventType.CANDLE):
            logger.debug('candles',e)
            self.candles[e.eventSymbol] = e

    async def _update_summaries(self):
        async for e in self.streamer.listen(EventType.SUMMARY):
            logger.debug('summaries',e)
            self.summaries[e.eventSymbol] = e

    async def _update_trades(self):
        async for e in self.streamer.listen(EventType.TRADE):
            logger.info('trades',e)
            self.trades[e.eventSymbol] = e

# sample eventSymbol ".TSLA240927C105"
PATTERN = r"\.([A-Z]+)(\d{6})([CP])(\d+)"

def parse_symbol(eventSymbol):
    matched = re.match(PATTERN,eventSymbol)
    ticker = matched.group(1)
    expiration = datetime.datetime.strptime(matched.group(2),'%y%m%d').date()
    contract_type = matched.group(3)
    strike = float(matched.group(4))
    return ticker,expiration,contract_type,strike

#
# is there a popular library with gex computation?
#
def get_gex_df(ticker,underlying,options_dict):
    spot_price = underlying.candles[ticker].close
    spot_price = np.array(spot_price).astype(float)
    mylist = []
    for k,v in options_dict.items():
        contract_list = []
        contract_list.extend(v.calls)
        contract_list.extend(v.puts)
        for x in contract_list:
            symbol = x.streamer_symbol
            ticker,expiration,contractType,strike = parse_symbol(symbol)
            gamma = v.greeks[symbol].gamma if symbol in v.greeks.keys() else np.nan
            candleBidVolume = v.candles[symbol].bidVolume if symbol in v.candles.keys() else np.nan
            candleAskVolume = v.candles[symbol].askVolume if symbol in v.candles.keys() else np.nan
            candleDayVolume = v.candles[symbol].volume if symbol in v.candles.keys() else np.nan
            tradeDayVolume = v.trades[symbol].dayVolume if symbol in v.trades.keys() else np.nan
            prevDayVolume = v.summaries[symbol].prevDayVolume if symbol in v.summaries.keys() else np.nan
            openInterest = v.summaries[symbol].openInterest if symbol in v.summaries.keys() else np.nan
            
            row = dict(
                symbol=symbol,
                ticker=ticker,
                expiration=expiration,
                contract_type=contractType,
                strike=strike,
                gamma=gamma,
                candleBidVolume=candleBidVolume,
                candleAskVolume=candleAskVolume,
                candleDayVolume=candleDayVolume,
                tradeDayVolume=tradeDayVolume,
                prevDayVolume=prevDayVolume,
                openInterest=openInterest,
            )
            mylist.append(row)
    
    df = pd.DataFrame(mylist)
    df['contract_type_int'] = df.contract_type.apply(lambda x: 1 if x=='C' else -1)
    #
    # TODO: once you gather some data
    # **this is where you can get juicy**
    # unleash your inner-data-scientist-self.
    # 
    df['spot_price'] = spot_price
    df['gexSummaryOpenInterest'] = df['gamma'].astype(float) * df['openInterest'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    df['gexCandleDayVolume'] = df['gamma'].astype(float) * df['candleDayVolume'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    df['gexTradeDayVolume'] = df['gamma'].astype(float) * df['tradeDayVolume'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    df['gexPrevDayVolume'] = df['gamma'].astype(float) * df['prevDayVolume'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    return df

async def cache_underlying(session,ticker,json_file):

    underlying = await UnderlyingLivePrices.create(session, ticker)
    spot_price = underlying.candles[ticker].close
    with open(json_file,'w') as f:
        item = dict(underlying.candles[ticker])
        f.write(json.dumps(item,indent=4,sort_keys=True,default=str))

async def cache_option_chain(session,ticker,csv_file,expiration_count=1):

    underlying = await UnderlyingLivePrices.create(session, ticker)

    chain = get_option_chain(session, ticker)

    options_dict = {}
    for expiration in sorted(list(chain.keys())):
        options_dict[expiration] = await OptionsLivePrices.create(session, ticker, expiration)
        if len(options_dict)==expiration_count:
            break

    df = get_gex_df(ticker,underlying,options_dict)
    df.to_csv(csv_file,index=False)

def time_to_datetime(tstamp):
    return datetime.datetime.fromtimestamp(float(tstamp) / 1e3)

def get_underlying(folder_path,resample=None,lookback_tstamp=None):
    json_list = sorted(str(x) for x in pathlib.Path(folder_path).rglob("*.json"))
    underlying_list = []
    for json_file in json_list:
        with open(json_file,'r') as f:
            content = json.loads(f.read())
            underlying_list.append(content)

    df = pd.DataFrame(underlying_list)
    df['tstamp'] = df.time.apply(time_to_datetime)
    df = df.set_index('tstamp')
    if resample is None:
        pass
    else:
        df = df[['time','eventSymbol','open','high','low','close']]
        mapper = {
            "open":  "first",
            "high":  "max",
            "low":   "min",
            "close": "last",
            "time": "last",
        }
        df = df.groupby(pd.Grouper(freq=resample)).agg(mapper)
        df = df.dropna()
        df['tstamp'] = df.time.apply(time_to_datetime)
    
    return df
#
# TODO: implement scroll bar to scroll through time and plot gex
#
def get_option_chain_df(folder_path,lookback_tstamp=None):
    csv_list = sorted(str(x) for x in pathlib.Path(folder_path).rglob("*.csv"))
    gex_df_list = []
    if lookback_tstamp == "last":
        csv_list = [csv_list[-1]]
    elif lookback_tstamp == "all":
        pass
    else:
        raise NotImplementedError()
    
    # 
    # TODO: resampling / data tally here is required!
    #
    #  + per https://github.com/tastyware/tastytrade/blob/master/tastytrade/dxfeed/candle.py
    # 
    #    candle volume is the total volume of the candle
    #    first figure out the frequecy of the event data for quote and greeks
    #    probably better to sum every 30sec/1min?
    #   
    #    this would mean you need to figure out if you can gather all the chain or just 0dte/single-expiry
    #    and if you can afford do that every second. 
    #     
    #    then think about if you can do multiple tickers...
    # 
    for csv_file in csv_list:
        df = pd.read_csv(csv_file)
        df['csv_file']=csv_file
        gex_df_list.append(df)
    return gex_df_list
    
if __name__ == "__main__":
    ticker = sys.argv[1]
    tstamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    workdir = os.path.join(shared_dir,ticker)
    os.makedirs(workdir,exist_ok=True)
    json_file = os.path.join(workdir,f'underlying-{tstamp}.json')
    session = get_session()
    output = asyncio.run(cache_underlying(session,ticker,json_file))
    print(json_file)