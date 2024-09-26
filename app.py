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
    get_data_df,
)
from plot_utils import plot_gex, get_png_file_paths

app = Flask(__name__,
    static_url_path='', 
    static_folder='static',
    template_folder='templates',
)

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
    tickers = request.args.to_dict()['tickers']
    resp = make_response(jsonify({"tickers":tickers}))
    resp.headers['HX-Redirect'] = url_for("gex",tickers=tickers)
    return resp

@app.route('/gex', methods=['GET'])
def gex():
    tickers = request.args.to_dict()['tickers']
    ticker_list = [x.upper() for x in tickers.split(",") if len(x)>0]
    is_test = is_test_func()
    return render_template('gex.html',ticker_list=ticker_list,is_test=is_test)

# setup cron via client side, yay or nay?
@app.route('/underlying-ping', methods=['GET'])
def underlying_ping():
    secrets = None
    message = None
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
    secrets = None
    message = None
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

@app.route('/png/<ticker>/<kind>')
def png_file(ticker,kind):
    try:
        gex_png_file, price_png_file = get_png_file_paths(ticker)
        if kind == 'price':
            return send_file(price_png_file,max_age=0)
        if kind == 'gex':
            return send_file(gex_png_file,max_age=0)
    except:
        return jsonify({"message":traceback.format_exc()})

@app.route('/gex-plot', methods=['GET'])
def gex_plot():
    spot_price = None
    underlying_tstamp = None
    option_tstamp = None
    message = None
    try:
        ticker = request.args.to_dict()['ticker']
        workdir = os.path.join(shared_dir,ticker)
        if os.path.exists(workdir):

            underlying_df, gex_df_list = get_data_df(workdir)

            plot_gex(workdir)

            spot_price = float(underlying_df.iloc[-1].close)
            underlying_tstamp = str(underlying_df.iloc[-1].tstamp)
            csv_basename = os.path.basename(gex_df_list[-1].iloc[-1].csv_file)
            option_tstamp = csv_basename.replace(".csv","").replace("option-chain-","")
    except:
        message = traceback.format_exc()
    return render_template('gexplot.html',
        message=message,
        ticker=ticker,
        option_tstamp=option_tstamp,
        underlying_tstamp=underlying_tstamp,
        spot_price=spot_price)
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("port",type=int)
    args = parser.parse_args()
    app.run(debug=True,host="0.0.0.0",port=args.port)

