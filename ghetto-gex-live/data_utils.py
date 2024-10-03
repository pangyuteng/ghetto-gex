
import logging
logger = logging.getLogger(__file__)

import os
import re
import sys
import uuid
import ast
import time
import math
import traceback
import datetime
import json
import pathlib

import pandas as pd
import numpy as np

import uuid
import aiofiles
import aiofiles.os
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

#
# below are copy pastas authored by Graeme22
# amazing stuff!!!
# https://tastyworks-api.readthedocs.io/en/latest/data-streamer.html#advanced-usage
# commit https://github.com/tastyware/tastytrade/blob/97e1bc6632cfd4a15721da816085eb906a02bcb0/docs/data-streamer.rst#L76
#

async def save_data_to_json(ticker,streamer_symbols,event_type,event):
    tstamp = now_in_new_york().strftime("%Y-%m-%d-%H-%M-%S.%f")
    daystamp = now_in_new_york().strftime("%Y-%m-%d")
    workdir = os.path.join(shared_dir,ticker,daystamp,streamer_symbols,event_type)
    await aiofiles.os.makedirs(workdir,exist_ok=True)
    uid = uuid.uuid4().hex
    json_file = os.path.join(workdir,f'{tstamp}-uid-{uid}.json')
    async with aiofiles.open(json_file,'w') as f:
        event_dict = dict(event)
        await f.write(json.dumps(event_dict,indent=4,sort_keys=True,default=str))


#
# below are copy pastas authored by Graeme22
# amazing stuff!!!
# https://tastyworks-api.readthedocs.io/en/latest/data-streamer.html#advanced-usage
# commit https://github.com/tastyware/tastytrade/blob/97e1bc6632cfd4a15721da816085eb906a02bcb0/docs/data-streamer.rst#L76
# # interval '15s', '5m', '1h', '3d',
CANDLE_TYPE = '15s'
@dataclass
class LivePrices:
    quotes: dict[str, Quote]
    greeks: dict[str, Greeks]
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
        expiration = sorted(list(chain.keys()))[0]
        options = [o for o in chain[expiration]]
        # the `streamer_symbol` property is the symbol used by the streamer
        streamer_symbols = [o.streamer_symbol for o in options]

        streamer = await DXLinkStreamer.create(session)
        # subscribe to quotes and greeks for all options on that date
        await streamer.subscribe(EventType.QUOTE, [ticker] + streamer_symbols)
        await streamer.subscribe(EventType.SUMMARY, streamer_symbols)
        await streamer.subscribe(EventType.TRADE, streamer_symbols)
        await streamer.subscribe(EventType.GREEKS, streamer_symbols)
        
        start_time = now_in_new_york()
        start_time = datetime.datetime(start_time.year,start_time.month,start_time.day,9,30,0)
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
        while len(self.quotes) < 1 or len(self.candles) < 1 or len(self.greeks) < 1 or len(self.summaries) < 1 or len(self.trades) < 1:
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
            self.quotes[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.QUOTE,e)

    async def _update_candles(self):
        async for e in self.streamer.listen(EventType.CANDLE):
            streamer_symbols = e.eventSymbol.replace("{="+CANDLE_TYPE+",tho=true}","")
            self.candles[streamer_symbols] = e
            await save_data_to_json(self.ticker,streamer_symbols,EventType.CANDLE,e)

    async def _update_summaries(self):
        async for e in self.streamer.listen(EventType.SUMMARY):
            self.summaries[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.SUMMARY,e)

    async def _update_trades(self):
        async for e in self.streamer.listen(EventType.TRADE):
            self.trades[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.TRADE,e)

    async def _update_greeks(self):
        async for e in self.streamer.listen(EventType.GREEKS):
            self.greeks[e.eventSymbol] = e
            await save_data_to_json(self.ticker,e.eventSymbol,EventType.GREEKS,e)

def get_cancel_file(ticker):
    return f"/tmp/cancel-{ticker}.txt"

def get_running_file(ticker):
    return f"/tmp/running-{ticker}.txt"

async def background_subscribe(ticker,session):
    try:

        running_file = get_running_file(ticker)
        cancel_file = get_cancel_file(ticker)
        if not os.path.exists(running_file):
            pathlib.Path(running_file).touch()

        live_prices = await LivePrices.create(session,ticker)

        while True:

            # Print or process the quotes in real time
            logger.info(f"Current quotes: {live_prices.quotes}")
            logger.info(f"Current candles: {live_prices.candles}")
            logger.info(f"Current summaries: {live_prices.summaries}")
            logger.info(f"Current trades {live_prices.trades}")
            pathlib.Path(running_file).touch()
            await asyncio.sleep(5)
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

def time_to_datetime(tstamp):
    return datetime.datetime.fromtimestamp(float(tstamp) / 1e3)


def get_candle_tstamp_list(ticker):
    ticker_Folder = os.path.join(shared_dir,ticker)
    candle_json_file_list = []
    for x in os.listdir(ticker_Folder):
        date_folder = os.path.join(ticker_Folder,x,ticker)
        tmp_list = [str(x) for x in pathlib.Path(date_folder).rglob("*Candle/*.json")]
        candle_json_file_list.extend(tmp_list)

    candle_tstamp_list = sorted(list(set([os.path.basename(x).split(".")[0] for x in candle_json_file_list])))
    return candle_tstamp_list

def get_underlying_df(ticker,tstamp,resample=None,tstamp_filter=None):

    daystamp = tstamp.strftime("%Y-%m-%d")
    candle_folder_path = os.path.join(shared_dir,ticker,daystamp,ticker,'Candle')
    
    if tstamp_filter is None:
        json_list = sorted(str(x) for x in pathlib.Path(candle_folder_path).rglob("*.json"))
    else:
        json_list = sorted(str(x) for x in pathlib.Path(candle_folder_path).rglob(f"{tstamp_filter}*.json"))

    underlying_list = []
    for json_file in json_list:
        with open(json_file,'r') as f:
            content = json.loads(f.read())
            underlying_list.append(content)

    df = pd.DataFrame(underlying_list)
    if len(df)>0:
        df = df[df.time.notnull()]

    if len(underlying_list)>0:
        df['tstamp'] = df.time.apply(time_to_datetime)
        df = df.set_index('tstamp')
    if resample is None:
        pass
    else:
        df = df[['time','eventSymbol','open','high','low','close']]
        df = df.dropna()
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
#def get_gex_df(ticker,underlying,options_dict):
# lookback_HMSFFFF LOL this is so bad
def get_gex_df(ticker,tstamp,tstamp_filter):

    underlying_df = get_underlying_df(ticker,tstamp)
    try:
        spot_price = float(underlying_df.iloc[-1].close)
        spot_price = np.array(spot_price).astype(float)
    except:
        spot_price = np.nan
        logger.error(traceback.format_exc())
        return pd.DataFrame([])

    daystamp = tstamp.strftime("%Y-%m-%d")
    folder_path = os.path.join(shared_dir,ticker,daystamp)
    contract_folder_list =  sorted([os.path.join(folder_path,x) for x in os.listdir(folder_path) if f".{ticker}" in x])
    
    mylist = []
    for contract_folder in contract_folder_list:
        # Candle  Greeks  Quote  Summary  Trade
        greeks_folder = os.path.join(contract_folder,"Greeks")
        candle_folder = os.path.join(contract_folder,"Candle")
        summary_folder = os.path.join(contract_folder,"Summary")
        greeks_file_list = sorted([str(x) for x in pathlib.Path(greeks_folder).rglob(f"{tstamp_filter}*.json")])
        candle_file_list = sorted([str(x) for x in pathlib.Path(candle_folder).rglob(f"{tstamp_filter}*.json")])
        summary_file_list = sorted([str(x) for x in pathlib.Path(summary_folder).rglob(f"{tstamp_filter}*.json")])
        streamer_symbol = os.path.basename(contract_folder)


        ticker,expiration,contractType,strike = parse_symbol(streamer_symbol)
        greeks_dict = {}
        candle_dict = {}
        summary_dict = {}

        if len(greeks_file_list)>0:
            greeks_file = greeks_file_list[-1]
            with open(greeks_file,'r') as f:
                greeks_dict = json.loads(f.read())

        if len(candle_file_list)>0:
            candle_file = candle_file_list[-1]
            with open(candle_file,'r') as f:
                candle_dict = json.loads(f.read())

        if len(summary_file_list)>0:
            summary_file = summary_file_list[-1]
            with open(summary_file,'r') as f:
                summary_dict = json.loads(f.read())

        # maye not a good idea to put 0
        if len(greeks_dict)>0:
            gamma = greeks_dict['gamma']
        else:
            gamma = 0

        if len(candle_dict)>0:
            candleDayVolume = candle_dict['volume']
        else:
            candleDayVolume = 0

        if len(summary_dict)>0:
            openInterest = summary_dict['openInterest']
        else:
            openInterest = 0
            
        row = dict(
            symbol=streamer_symbol,
            ticker=ticker,
            expiration=expiration,
            contract_type=contractType,
            strike=strike,
            gamma=gamma,
            candleDayVolume=candleDayVolume,
            openInterest=openInterest,
        )
        mylist.append(row)

    df = pd.DataFrame(mylist)
    df['contract_type_int'] = df.contract_type.apply(lambda x: 1 if x=='C' else -1)
    #
    # TODO:
    # + [ ] unit is not right check below perfiliev blog
    #       https://perfiliev.com/blog/how-to-calculate-gamma-exposure-and-zero-gamma-level
    #       https://github.com/Matteo-Ferrara/gex-tracker/blob/068584c849a7cd683319250fe81c3a3847716950/main.py#L79
    #
    # + [ ] add unit,label to charts
    # 

    df['spot_price'] = spot_price
    df['gexSummaryOpenInterest'] = df['gamma'].astype(float) * df['openInterest'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    df['gexCandleDayVolume'] = df['gamma'].astype(float) * df['candleDayVolume'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    return df

#
# TODO: once you gather some data
# **this is where shit gets juicy**
# unleash your inner-data-scientist-self.
# 

#
# TODO: implement scroll bar to scroll through time and plot gex
#
def get_option_chain_df(folder_path,lookback_tstamp=None):
    raise NotImplementedError()
    
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,#level=logging.DEBUG,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    ticker = sys.argv[1]
    action = sys.argv[2]
    
    if action == "background_subscribe":
        session = get_session()
        output = asyncio.run(background_subscribe(ticker,session))
    
    
    if action == "get_underlying_df":
        tstamp = now_in_new_york()
        df = get_underlying_df(ticker,tstamp,resample=None)
        print(df.shape)
        if len(df) > 0:
            print(dict(df.iloc[-1]))
        df = get_underlying_df(ticker,tstamp,resample="1Min")
        print(df.shape)
        if len(df) > 0:
            print(dict(df.iloc[-1]))
    
    if action == "get_gex_df":
        tstamp = now_in_new_york()
        df = get_gex_df(ticker,tstamp,tstamp_filter="2024-09-30-16")
        
"""
cd ..

docker run -it -u $(id -u):$(id -g) -p 80:80 \

docker run -it -p 80:80 \
    --env-file .env \
    -v ghetto-gex-live_shared:/shared \
    -v $PWD:/opt/app \
    -w /opt/app pangyuteng/ghetto-gex-live:latest bash

export SHARED_DIR=/shared
python data_utils.py SPX

"""