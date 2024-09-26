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
    redirect, url_for, jsonify, make_response
)

import asyncio
from data_utils import Session, cache_gex_csv, get_session

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
    except:
        app.logger.error(traceback.format_exc())
        message = "unable to login with credentials in .env file!"

    return render_template('index.html',session=session,message=message)

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
    return render_template('gex.html',ticker_list=ticker_list)

# setup cron via client side, yay or nay?
@app.route('/gex-ping', methods=['GET'])
def gex_ping():
    secrets = None
    message = None
    try:
        ticker = request.args.to_dict()['ticker']

        tstamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        workdir = os.path.join(shared_dir,ticker)
        os.makedirs(workdir,exist_ok=True)

        csv_file = os.path.join(workdir,f'gex-{tstamp}.csv')
        json_file = os.path.join(workdir,f'spot-{tstamp}.json')

        session = get_session()
        asyncio.run(cache_gex_csv(session,ticker,csv_file,json_file,expiration_count=1))

        message = {"json_found":os.path.exists(json_file),"csv_found":os.path.exists(csv_file),"tstamp":tstamp}
        return jsonify(message), 200
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/gex-plot', methods=['GET'])
def gex_plot():
    message = None
    file_list = []
    try:
        ticker = request.args.to_dict()['ticker']
        workdir = os.path.join(shared_dir,ticker)
        if os.path.exists(workdir):
            file_list = [os.path.join(workdir,x) for x in os.listdir(workdir)]
    except:
        message = traceback.format_exc()
    return render_template('gexplot.html',message=message,file_list=file_list)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("port",type=int)
    args = parser.parse_args()
    app.run(debug=True,host="0.0.0.0",port=args.port)

