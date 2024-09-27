import logging
logger = logging.getLogger(__file__)
import traceback
import os
import sys
import ast
import pathlib
import argparse
import datetime

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

@app.route('/data/<ticker>/<kind>')
def get_data(ticker,kind):
    try:
        workdir = os.path.join(shared_dir,ticker)
        if kind == 'underlying':
            underlying_df = get_underlying(workdir)
            underlying_tstamp = str(underlying_df.iloc[-1].tstamp)
            data_json = underlying_df.iloc[-1].to_json()
            return data_json
        elif kind == 'optionchain':
            gex_df_list = get_option_chain_df(workdir,limit_last=True)
            csv_basename = os.path.basename(gex_df_list[-1].iloc[-1].csv_file)
            option_tstamp = csv_basename.replace(".csv","").replace("option-chain-","")
            data_json = gex_df_list[-1].to_dict('records')
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
        return render_template('gexplot.html',ticker=ticker,underlying=underlying,optionchain=optionchain)
    except:
        app.logger.error(traceback.format_exc())
        return jsonify({"message":traceback.format_exc()}),400
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("port",type=int)
    args = parser.parse_args()
    app.run(debug=True,host="0.0.0.0",port=args.port)

