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

from quart import (
    Quart, render_template, request,
    url_for, jsonify, make_response,
)

import asyncio

from data_utils import (
    get_session,is_test_func,
    get_cancel_file, get_running_file, 
    background_subscribe, 
    get_underlying_df,get_gex_df,now_in_new_york
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

@app.route('/cancel-sub', methods=['GET'])
async def cancel_sub():
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
        tickers = request.args.to_dict()['tickers']
        ticker_list = [x.upper() for x in tickers.split(",") if len(x) > 0]
        for ticker in ticker_list:
            running_file = get_running_file(ticker)
            cancel_file = get_cancel_file(ticker)
            if os.path.exists(cancel_file):
                os.remove(cancel_file)
            if not os.path.exists(running_file):
                app.add_background_task(background_subscribe,ticker,session)
                resp = await make_response(jsonify({"tickers":ticker}))
            else:
                resp = await make_response(jsonify({"message":f"{ticker} job running already"}))
        # TODO: make up your mind on ticker or tickerS
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
def get_data(ticker,kind):
    tstamp = now_in_new_york()
    underlying_df = get_underlying_df(ticker,tstamp,resample=None)
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
        tstamp = now_in_new_york()
        dayfilter = tstamp.strftime("%Y-%m-%d")
        df = get_gex_df(ticker,tstamp,tstamp_filter=dayfilter)
        if len(df) == 0:
            return []
        df = df[(df.strike>price_min)&(df.strike<price_max)]
        df = df.sort_values(['strike'],ascending=False)
        data_json = df.to_dict('records')
        return data_json
    else:
        raise NotImplementedError()


@app.route('/gex-plot', methods=['GET'])
async def gex_plot():
    try:
        ticker = request.args.to_dict()['ticker']
        refreshonly = True if request.args.to_dict()['refreshonly']=='true' else False

        trigger_tstamp = now_in_new_york()
        underlying = get_data(ticker,'underlying')
        optionchain = get_data(ticker,'optionchain')

        strike_list = sorted(list(set([x['strike'] for x in optionchain])),reverse=True)
        strike_list = [int(x) for x in strike_list]
        put_gexCandleDayVolume = [x['gexCandleDayVolume'] for x in optionchain if x['contract_type']=="P"]
        put_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="P"]
        call_gexCandleDayVolume = [x['gexCandleDayVolume'] for x in optionchain if x['contract_type']=="C"]
        call_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="C"]
        try:
            spot_price = float(underlying[-1]['close'])
        except:
            app.logger.warning(traceback.format_exc())
            spot_price = -1

        # TODO: determine range to show. past 30min
        time_list = [x['time'] for x in underlying]
        max_tstamp = max(time_list)
        LOOKBACK_SEC = 2*60*30
        min_tstamp = max_tstamp-1000*LOOKBACK_SEC
        underlying = [x for x in underlying if x['time']>min_tstamp]

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
            sorted_optionchain = sorted(optionchain,key=lambda x:x['gexCandleDayVolume'])
            positive_y = int(sorted_optionchain[-1]['strike'])
            negative_y = int(sorted_optionchain[0]['strike'])
        except:
            app.logger.warning(traceback.format_exc())
            positive_y = 0
            negative_y = 0
        app.logger.info(f"axhlines {positive_y} {negative_y}")
        app.logger.info(f"refreshonly {refreshonly}")

        if refreshonly:
            html_basename =  'gex-refresh-charts.html'
        else:
            html_basename = 'gexplot.html'

        return await render_template(html_basename,
            ticker=ticker,
            spot_price=spot_price,
            strike_list=strike_list,
            put_gexCandleDayVolume=put_gexCandleDayVolume,
            put_gexSummaryOpenInterest=put_gexSummaryOpenInterest,
            call_gexCandleDayVolume=call_gexCandleDayVolume,
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
    args = parser.parse_args()
    app.run(debug=True,host="0.0.0.0",port=args.port)

