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

from flask import (
    Flask, request, render_template, Response,
    redirect, url_for, jsonify, make_response,
    send_file
)

import asyncio
from data_utils import (
    Session, get_session, is_test_func,
    cache_underlying, cache_option_chain,
    get_underlying, get_option_chain_df
)


app = Flask(__name__,
    static_url_path='', 
    static_folder='static',
    template_folder='templates',
)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
shared_dir = os.environ.get("SHARED_DIR")

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify("pong")

@app.route('/', methods=['GET'])
def index():
    message = None
    session = None
    try:
        session = get_session()
        is_test = is_test_func()
    except:
        app.logger.error(traceback.format_exc())
        message = "unable to login with credentials in .env file!"

    return render_template('index.html',session=session,message=message,is_test=is_test)

@app.route('/login', methods=['GET'])
def login():
    try:
        tickers = request.args.to_dict()['tickers']
        resp = make_response(jsonify({"tickers":tickers}))
        resp.headers['HX-Redirect'] = url_for("gex",tickers=tickers)
        return resp
    except:
        return jsonify({"message":traceback.format_exc()}),400
@app.route('/gex', methods=['GET'])
def gex():
    try:
        tickers = request.args.to_dict()['tickers']
        ticker_list = [x.upper() for x in tickers.split(",") if len(x)>0]
        is_test = is_test_func()
        return render_template('gex.html',ticker_list=ticker_list,is_test=is_test)
    except:
        return jsonify({"message":traceback.format_exc()}),400
# setup cron via client side, yay or nay?
@app.route('/underlying-ping', methods=['GET'])
def underlying_ping():
    try:
        ticker = request.args.to_dict()['ticker']

        tstamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        workdir = os.path.join(shared_dir,ticker)
        os.makedirs(workdir,exist_ok=True)

        json_file = os.path.join(workdir,f'underlying-{tstamp}.json')

        session = get_session()
        asyncio.run(cache_underlying(session,ticker,json_file))

        message = {"underlying_file_found":os.path.exists(json_file),"tstamp":tstamp}
        return jsonify(message), 200
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/optionchain-ping', methods=['GET'])
def optionchain_ping():
    try:
        ticker = request.args.to_dict()['ticker']

        tstamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        workdir = os.path.join(shared_dir,ticker)
        os.makedirs(workdir,exist_ok=True)

        csv_file = os.path.join(workdir,f'option-chain-{tstamp}.csv')

        session = get_session()
        asyncio.run(cache_option_chain(session,ticker,csv_file,expiration_count=1))

        message = {"optionchain_file_found":os.path.exists(csv_file),"tstamp":tstamp}
        return jsonify(message), 200
    except:
        return jsonify({"message":traceback.format_exc()}),400

#
# TODO: need a python df + class for option chains funcs.
#
PRCT_NEG,PRCT_POS = 0.96,1.04
@app.route('/data/<ticker>/<kind>')
def get_data(ticker,kind):
    try:
        workdir = os.path.join(shared_dir,ticker)
        underlying_df = get_underlying(workdir)
        if kind == 'underlying':
            underlying_df.replace(np.nan, None,inplace=True)
            data_json = underlying_df.to_dict('records')
            return data_json
        elif kind == 'optionchain':

            close = float(underlying_df.iloc[-1].close)

            xmin, xmax = close*PRCT_NEG,close*PRCT_POS
            gex_df_list = get_option_chain_df(workdir,limit_last=True)
            df = gex_df_list[-1].copy()
            df = df[(df.strike>xmin)&(df.strike<xmax)]
            df = df.sort_values(['strike'],ascending=False)
            df.replace(np.nan, None,inplace=True)
            last_option_tstamp = os.path.basename(df.csv_file.iloc[-1]).replace(".csv","").replace("option-chain-","")
            app.logger.debug(f"last_option_tstamp {last_option_tstamp}")
            data_json = df.to_dict('records')
            return data_json
        else:
            raise NotImplementedError()
    except:
        app.logger.error(traceback.format_exc())
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/gex-plot', methods=['GET'])
def gex_plot():
    try:
        ticker = request.args.to_dict()['ticker']

        underlying = get_data(ticker,'underlying')
        
        optionchain = get_data(ticker,'optionchain')
        strike_list = sorted(list(set([x['strike'] for x in optionchain])),reverse=True)
        strike_list = [int(x) for x in strike_list]
        xmin, xmax = min(strike_list), max(strike_list)
        put_gexCandleDayVolume = [x['gexCandleDayVolume'] for x in optionchain if x['contract_type']=="P"]
        put_gexPrevDayVolume = [x['gexPrevDayVolume'] for x in optionchain if x['contract_type']=="P"]
        put_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="P"]
        call_gexCandleDayVolume = [x['gexCandleDayVolume'] for x in optionchain if x['contract_type']=="C"]
        call_gexPrevDayVolume = [x['gexPrevDayVolume'] for x in optionchain if x['contract_type']=="C"]
        call_gexSummaryOpenInterest = [x['gexSummaryOpenInterest'] for x in optionchain if x['contract_type']=="C"]
        
        spot_price = float(underlying[-1]['close'])

        time_list = [x['time'] for x in underlying]
        max_tstamp = max(time_list)
        min_tstamp = max_tstamp-1000*100
        underlying = [x for x in underlying if x['time']>min_tstamp]
        time_min = f"new Date({min_tstamp})"
        time_max = f"new Date({max_tstamp})"
        positive_y = 5800
        negative_y = 5700

        return render_template('gexplot.html',
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
            xmin=xmin,
            xmax=xmax,
        )
    except:
        app.logger.error(traceback.format_exc())
        return jsonify({"message":traceback.format_exc()}),400
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("port",type=int)
    args = parser.parse_args()
    app.run(debug=True,host="0.0.0.0",port=args.port)

