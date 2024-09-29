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
    get_session, is_test_func,
    cache_underlying, cache_option_chain,
    get_underlying, get_option_chain_df
)


app = Quart(__name__,
    static_url_path='', 
    static_folder='static',
    template_folder='templates',
)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
shared_dir = os.environ.get("SHARED_DIR")

@app.route('/ping', methods=['GET'])
async def ping():
    return jsonify("pong")

@app.route('/', methods=['GET'])
async def index():
    message = None
    session = None
    try:
        session = get_session()
        is_test = is_test_func()
    except:
        app.logger.error(traceback.format_exc())
        message = "unable to login with credentials in .env file!"

    return await render_template('index.html',session=session,message=message,is_test=is_test)

@app.route('/subscribe', methods=['GET'])
async def subscribe():
    try:
        tickers = request.args.to_dict()['tickers']
        resp = await make_response(jsonify({"tickers":tickers}))
        resp.headers['HX-Redirect'] = url_for("gex",tickers=tickers)
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
# setup cron via client side, yay or nay?
@app.route('/underlying-ping', methods=['GET'])
async def underlying_ping():
    try:
        ticker = request.args.to_dict()['ticker']

        tstamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        workdir = os.path.join(shared_dir,ticker)
        os.makedirs(workdir,exist_ok=True)

        json_file = os.path.join(workdir,f'underlying-{tstamp}.json')

        session = get_session()
        await cache_underlying(session,ticker,json_file)

        message = {"underlying_file_found":os.path.exists(json_file),"tstamp":tstamp}
        return jsonify(message), 200
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/optionchain-ping', methods=['GET'])
async def optionchain_ping():
    try:
        ticker = request.args.to_dict()['ticker']

        tstamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        workdir = os.path.join(shared_dir,ticker)
        os.makedirs(workdir,exist_ok=True)

        csv_file = os.path.join(workdir,f'option-chain-{tstamp}.csv')

        session = get_session()
        await cache_option_chain(session,ticker,csv_file,expiration_count=1)

        message = {"optionchain_file_found":os.path.exists(csv_file),"tstamp":tstamp}
        return jsonify(message), 200
    except:
        return jsonify({"message":traceback.format_exc()}),400

#
# TODO: need a python df + class for option chains funcs.
#
PRCT_NEG,PRCT_POS = 0.98,1.02
def get_data(ticker,kind,lookback_tstamp=None):
    workdir = os.path.join(shared_dir,ticker)
    underlying_df = get_underlying(workdir,resample="1Min",lookback_tstamp=None)
    if kind == 'underlying':
        underlying_df.replace(np.nan, None,inplace=True)
        data_json = underlying_df.to_dict('records')
        return data_json
    elif kind == 'optionchain':

        close = float(underlying_df.iloc[-1].close)

        price_min, price_max = close*PRCT_NEG,close*PRCT_POS
        gex_df_list = get_option_chain_df(workdir,lookback_tstamp="last")
        df = gex_df_list[-1].copy()
        df = df[(df.strike>price_min)&(df.strike<price_max)]
        df = df.sort_values(['strike'],ascending=False)
        df.replace(np.nan, None,inplace=True)
        last_option_tstamp = os.path.basename(df.csv_file.iloc[-1]).replace(".csv","").replace("option-chain-","")
        app.logger.debug(f"last_option_tstamp {last_option_tstamp}")
        data_json = df.to_dict('records')
        return data_json
    else:
        raise NotImplementedError()

@app.route('/data/<ticker>/<kind>')
async def _data(ticker,kind,lookback_tstamp=None):
    try:
        return get_data(ticker,kind,lookback_tstamp=lookback_tstamp)
    except:
        app.logger.error(traceback.format_exc())
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/gex-plot', methods=['GET'])
async def gex_plot():
    try:
        ticker = request.args.to_dict()['ticker']
        refreshonly = True if request.args.to_dict()['refreshonly']=='true' else False
        lookback_tstamp = request.args.to_dict().get('tstamp',None)

        underlying = get_data(ticker,'underlying',lookback_tstamp=lookback_tstamp)
        optionchain = get_data(ticker,'optionchain',lookback_tstamp=lookback_tstamp)

        strike_list = sorted(list(set([x['strike'] for x in optionchain])),reverse=True)
        strike_list = [int(x) for x in strike_list]
        put_gexCandleDayVolume = [x['gexCandleDayVolume'] for x in optionchain if x['contract_type']=="P"]
        put_gexPrevDayVolume = [x['gexPrevDayVolume'] for x in optionchain if x['contract_type']=="P"]
        put_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="P"]
        call_gexCandleDayVolume = [x['gexCandleDayVolume'] for x in optionchain if x['contract_type']=="C"]
        call_gexPrevDayVolume = [x['gexPrevDayVolume'] for x in optionchain if x['contract_type']=="C"]
        call_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="C"]
        
        spot_price = float(underlying[-1]['close'])
        
        # TODO: determine range to show. past 30min
        time_list = [x['time'] for x in underlying]
        max_tstamp = max(time_list)
        LOOKBACK_SEC = 2*60*60
        min_tstamp = max_tstamp-1000*LOOKBACK_SEC
        underlying = [x for x in underlying if x['time']>min_tstamp]

        close_list = [float(x['close']) for x in underlying]
        price_min = min(close_list)-50
        price_max = max(close_list)+50

        time_min = f"new Date({min_tstamp})"
        time_max = f"new Date({max_tstamp})"
        try:
            sorted_optionchain = sorted(optionchain,key=lambda x:x['gexCandleDayVolume'])
            positive_y = float(sorted_optionchain[-1]['strike'])
            negative_y = float(sorted_optionchain[0]['strike'])
        except:
            app.logger.warning(traceback.format_exc())
            positive_y = spot_price
            negative_y = spot_price
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
            put_gexPrevDayVolume=put_gexPrevDayVolume,
            put_gexSummaryOpenInterest=put_gexSummaryOpenInterest,
            call_gexCandleDayVolume=call_gexCandleDayVolume,
            call_gexPrevDayVolume=call_gexPrevDayVolume,
            call_gexSummaryOpenInterest=call_gexSummaryOpenInterest,
            underlying=underlying,
            optionchain=optionchain,
            positive_y=positive_y,
            negative_y=negative_y,
            time_min=time_min,
            time_max=time_max,
            price_min=price_min,
            price_max=price_max,
        )
    except:
        app.logger.error(traceback.format_exc())
        return jsonify({"message":traceback.format_exc()}),400
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("port",type=int)
    args = parser.parse_args()
    app.run(debug=True,host="0.0.0.0",port=args.port)

