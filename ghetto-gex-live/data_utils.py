
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
    spot_price = underlying.candles[underlying.underlying.streamer_symbol].close
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
    df['gexTradeDayVolume'] = df['gamma'].astype(float) * df['tradeDayVolume'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    df['gexPrevDayVolume'] = df['gamma'].astype(float) * df['prevDayVolume'].astype(float) * 100 * spot_price * spot_price * 0.01 * df['contract_type_int']
    return df

#
# TODO: once you gather some data
# **this is where shit gets juicy**
# unleash your inner-data-scientist-self.
# 

def get_cancel_file(ticker):
    return f"/tmp/cancel-{ticker}.txt"

def get_running_file(ticker):
    return f"/tmp/running-{ticker}.txt"

async def background_subscribe(ticker,session,expiration_count=1):
    try:

        running_file = get_running_file(ticker)
        cancel_file = get_cancel_file(ticker)
        if not os.path.exists(running_file):
            pathlib.Path(running_file).touch()
        #TODO underlyingLiverPrices = await UnderlyingLivePrices.create(session,ticker)
        workdir = os.path.join(shared_dir,ticker)
        os.makedirs(workdir,exist_ok=True)

        while True:
            tstamp = now_in_new_york().strftime("%Y-%m-%d-%H-%M-%S.%f")
            json_file = os.path.join(workdir,f'underlying-{tstamp}.json')
            csv_file = os.path.join(workdir,f'option-chain-{tstamp}.csv')

            # Print or process the quotes in real time
            logger.info(f"Current quotes: {underlyingLiverPrices.quotes}")
            logger.info(f"Current candles: {underlyingLiverPrices.candles}")
            logger.info(f"Current summaries: {underlyingLiverPrices.summaries}")
            logger.info(f"Current trades {underlyingLiverPrices.trades}")
            pathlib.Path(running_file).touch()
            if os.path.exists(cancel_file):
                logger.info(f"canceljob receieved...")
                os.remove(cancel_file)
                logger.info(f"canceling!")
                await underlyingLiverPrices.shutdown()
                for k,option_obj in options_dict.items():
                    option_obj.shutdown()
                if os.path.exists(running_file):
                    os.remove(running_file)
                raise ValueError("canceljob")
            
            if underlyingLiverPrices.underlying.streamer_symbol in underlyingLiverPrices.candles.keys():
                with open(json_file,'w') as f:
                    item = dict(underlyingLiverPrices.candles[underlyingLiverPrices.underlying.streamer_symbol])
                    f.write(json.dumps(item,indent=4,sort_keys=True,default=str))

                df = get_gex_df(ticker,underlyingLiverPrices,options_dict)
                df.to_csv(csv_file,index=False)
            else:
                logger.info("NO SYMBOLS FOUND?????")
            await asyncio.sleep(15)
            # cache she here.
    except KeyboardInterrupt:
        logger.error("Stopping live price streaming...")
    finally:
        if os.path.exists(running_file):
            os.remove(running_file)

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
    if len(underlying_list)>0:
        df['tstamp'] = df.time.apply(time_to_datetime)
        df = df.set_index('tstamp')
        print(df.shape)
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
        print(df.time.unique())
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
    logging.basicConfig(
        level=logging.INFO,#level=logging.DEBUG,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    ticker = sys.argv[1]
    #session = get_session()
    #output = asyncio.run(background_subscribe(ticker,session))
    folder_path = '/shared/SPX'
    df = get_underlying(folder_path,resample=None,lookback_tstamp=None)
    print(dict(df.iloc[-1]))
    close = float(df.iloc[-1].close)
    print(close)
    df = get_option_chain_df(folder_path,lookback_tstamp="last")
    print(df[-1])
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