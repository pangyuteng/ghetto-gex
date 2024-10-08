import logging
logger = logging.getLogger(__file__)
import traceback
import os
import sys
import ast
import pathlib
import argparse
import datetime
import pandas as pd
import numpy as np
import requests
from quart import (
    Quart, render_template, request,
    url_for, jsonify, make_response,
)
import aiohttp
import asyncio

from data_utils import (
    get_session,is_test_func,
    get_cancel_file, get_running_file, 
    background_subscribe, 
    get_underlying_df,get_gex_df,
    now_in_new_york, get_candle_tstamp_list,
    tick_direction,
)

app = Quart(__name__,
    static_url_path='', 
    static_folder='static',
    template_folder='templates',
)

try:
    session = get_session()
except:
    session = None
    app.logger.error("tastytrade login failure")

shared_dir = os.environ.get("SHARED_DIR")

@app.route('/ping', methods=['GET'])
async def ping():
    return jsonify("pong")

@app.route('/', methods=['GET'])
async def index():
    message = None
    try:
        is_test = is_test_func()
    except:
        app.logger.error(traceback.format_exc())
        message = "unable to login with credentials in .env file!"

    return await render_template('index.html',session=session,message=message,is_test=is_test)

@app.route('/cancel', methods=['GET'])
async def cancel():
    try:
        ticker = request.args.to_dict()['ticker']
        ticker = ticker.upper()
        cancel_file = get_cancel_file(ticker)
        pathlib.Path(cancel_file).touch()
        await asyncio.sleep(10)
        print(f"!!!            {len(app.background_tasks)}")
        while len(app.background_tasks)>0:
           task = app.background_tasks.pop()
           task.cancel()
        print(f"!!!            {len(app.background_tasks)}")
        return jsonify({"message":f"{ticker} canceled"})
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/subscribe', methods=['GET'])
async def subscribe():
    try:
        ticker = request.args.get('ticker')
        running_file = get_running_file(ticker)
        cancel_file = get_cancel_file(ticker)
        if os.path.exists(cancel_file):
            os.remove(cancel_file)
        if not os.path.exists(running_file):
            app.add_background_task(background_subscribe,ticker,session)
            mydict = {'message':f"subscribtion added {ticker}"}
        else:
            mydict = {'message':f"already subscribed {ticker}"}
        return jsonify(mydict)
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/start-gex', methods=['GET'])
async def start_gex():
    try:
        tickers = request.args.to_dict()['tickers']
        ticker_list = [x.upper() for x in tickers.split(",") if len(x) > 0]
        myresp_list = []
        for ticker in ticker_list:
            get_url = f"http://background/subscribe?ticker={ticker}"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(get_url) as response:
                    myresp = await response.json()
                    myresp_list.append(myresp)
        resp = await make_response(jsonify({"status":myresp_list}))
        resp.headers['HX-Redirect'] = url_for("gex",tickers=ticker)
        return resp
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/gex', methods=['GET'])
async def gex():
    try:
        tickers = request.args.to_dict()['tickers']
        ticker_list = [x.upper() for x in tickers.split(",") if len(x)>0]
        is_test = is_test_func()
        return await render_template('gex.html',ticker_list=ticker_list,is_test=is_test)
    except:
        return jsonify({"message":traceback.format_exc()}),400


# TODO: need a python df + class for option chains funcs.
#
PRCT_NEG,PRCT_POS = 0.98,1.02
def get_data(ticker,kind,tstamp_filter):
    tstamp = now_in_new_york()
    underlying_df = get_underlying_df(ticker,tstamp,resample=None,tstamp_filter=tstamp_filter)
    if kind == 'underlying':
        underlying_df.replace(np.nan, None,inplace=True)
        if len(underlying_df) == 0:
            return []
        data_json = underlying_df.to_dict('records')
        return data_json
    elif kind == 'optionchain':
        if len(underlying_df) > 0:
            try:
                close = float(underlying_df.iloc[-1].close)
            except:
                close = np.nan
        else:
            close = np.nan

        price_min, price_max = close*PRCT_NEG,close*PRCT_POS
        df = get_gex_df(ticker,tstamp,tstamp_filter=tstamp_filter)
        if len(df) == 0:
            return []
        df = df[(df.strike>price_min)&(df.strike<price_max)]
        df = df.sort_values(['strike'],ascending=False)
        data_json = df.to_dict('records')
        return data_json
    else:
        raise NotImplementedError()

#
# TODO: https://apexcharts.com/javascript-chart-demos/heatmap-charts/color-range/
#
@app.route('/direction', methods=['GET'])
async def direction():
    try:
        trigger_tstamp = now_in_new_york()
        ticker = request.args.get('ticker')
        tstamp_filter = request.args.get('tstamp_filter',trigger_tstamp.strftime("%Y-%m-%d"))
        ret_dict = tick_direction(ticker,tstamp_filter)
        return jsonify(ret_dict)
    except:
        app.logger.error(traceback.format_exc())
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/gex-plot', methods=['GET'])
async def gex_plot():
    try:

        trigger_tstamp = now_in_new_york()
        ticker = request.args.get('ticker')
        tstamp_filter = request.args.get('tstamp_filter',trigger_tstamp.strftime("%Y-%m-%d"))
        refreshonly = True if request.args.get('refreshonly') == 'true' else False
        
        underlying = get_data(ticker,'underlying',tstamp_filter)
        optionchain = get_data(ticker,'optionchain',tstamp_filter)

        strike_list = sorted(list(set([x['strike'] for x in optionchain])),reverse=True)
        strike_list = [int(x) for x in strike_list]
        put_gexTradeDayVolume = [x['gextradeDayVolume'] for x in optionchain if x['contract_type']=="P"]
        put_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="P"]
        call_gexTradeDayVolume = [x['gextradeDayVolume'] for x in optionchain if x['contract_type']=="C"]
        call_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="C"]
        try:
            spot_price = float(underlying[-1]['close'])
        except:
            app.logger.warning(traceback.format_exc())
            spot_price = -1

        try:
            # TODO: determine range to show. past 30min
            time_list = [x['time'] for x in underlying]
            max_tstamp = max(time_list)
            LOOKBACK_SEC = 2*60*30
            min_tstamp = max_tstamp-1000*LOOKBACK_SEC
            underlying = [x for x in underlying if x['time']>min_tstamp]
        except:
            app.logger.warning(traceback.format_exc())
            max_tstamp = -1
            min_tstamp = -1

        try:
            close_list = [float(x['close']) for x in underlying if x['close'] is not None]
            price_min = min(close_list)-50
            price_max = max(close_list)+50
        except:
            app.logger.warning(traceback.format_exc())
            price_min = 0
            price_max = 0

        time_min = min_tstamp
        time_max = max_tstamp
        try:
            c_sorted_optionchain = sorted([x for x in optionchain if x['contract_type']=='C' and x['gexCandleDayVolume'] > 0 ],key=lambda x:x['gexCandleDayVolume'] )
            p_sorted_optionchain = sorted([x for x in optionchain if x['contract_type']=='P' and x['gexCandleDayVolume'] < 0 ],key=lambda x:x['gexCandleDayVolume'] )
            positive_y = float(c_sorted_optionchain[-1]['strike'])
            negative_y = float(p_sorted_optionchain[0]['strike'])
        except:
            app.logger.warning(traceback.format_exc())
            positive_y = 0
            negative_y = 0
        app.logger.info(f"axhlines {positive_y} {negative_y}")
        app.logger.info(f"refreshonly {refreshonly}")

        if refreshonly:
            html_basename =  'gex-refresh-charts.html'
            candle_tstamp_list = []
        else:
            html_basename = 'gexplot.html'
            candle_tstamp_list = get_candle_tstamp_list(ticker)

        return await render_template(html_basename,
            ticker=ticker,
            spot_price=spot_price,
            strike_list=strike_list,
            put_gexTradeDayVolume=put_gexTradeDayVolume,
            put_gexSummaryOpenInterest=put_gexSummaryOpenInterest,
            call_gexTradeDayVolume=call_gexTradeDayVolume,
            call_gexSummaryOpenInterest=call_gexSummaryOpenInterest,
            underlying=underlying,
            optionchain=optionchain,
            positive_y=positive_y,
            negative_y=negative_y,
            time_min=time_min,
            time_max=time_max,
            price_min=price_min,
            price_max=price_max,
            trigger_tstamp=trigger_tstamp,
            candle_tstamp_list=candle_tstamp_list,
        )
    except:
        app.logger.error(traceback.format_exc())
        return jsonify({"message":traceback.format_exc()}),400
    

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,#level=logging.DEBUG,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("port",type=int)
    parser.add_argument('-d', '--debug',action='store_true')
    args = parser.parse_args()
    app.run(debug=args.debug,host="0.0.0.0",port=args.port)

