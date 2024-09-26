import logging
logger = logging.getLogger(__file__)
import traceback
import os
import sys
import ast
import pathlib
import argparse
import datetime

import base64


from flask import (
    Flask, request, render_template, Response,
    redirect, url_for, jsonify, make_response
)

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
    return render_template('index.html')

@app.route('/login', methods=['GET'])
def login():
    secrets = None
    message = None
    try:
        secrets = request.args.to_dict()
        sample_string = str(secrets)
        sample_string_bytes = sample_string.encode("ascii")
        base64_bytes = base64.b64encode(sample_string_bytes)
        base64_token = base64_bytes.decode("ascii")
    except:
        message = traceback.format_exc()
    #
    # NOTE: ideally someone needs to pass me a token and this application use the token to acces dxLink.
    #
    resp = make_response(jsonify({"message":message}))
    resp.headers['HX-Redirect'] = url_for("gexpage",token=base64_token)
    return resp

import asyncio
from data_utils import Session, cache_gex_csv

@app.route('/gex', methods=['GET'])
def gex_main():
    token = request.args.to_dict()['token']
    return render_template('gex.html',token=token)

@app.route('/gex-plot', methods=['GET'])
def gex_plot():
    message = None
    try:
        base64_token = request.args.to_dict()['token']
        base64_bytes = base64_token.encode("ascii")
        sample_string_bytes = base64.b64decode(base64_bytes)
        sample_string = sample_string_bytes.decode("ascii")
        secrets = ast.literal_eval(sample_string)
        ticker = secrets['ticker'].upper()
        workdir = os.path.join(shared_dir,ticker)
    except:
        message = traceback.format_exc()
    return render_template('gexplot.html',message=message)

@app.route('/gex-ping', methods=['GET'])
def gex_ping():
    secrets = None
    message = None
    try:
        base64_token = request.args.to_dict()['token']

        base64_bytes = base64_token.encode("ascii")
        sample_string_bytes = base64.b64decode(base64_bytes)
        sample_string = sample_string_bytes.decode("ascii")
        secrets = ast.literal_eval(sample_string)
        app.logger.info(str(secrets))
        username = secrets['username']
        password = secrets['password']
        is_test = True if secrets['sandbox'] == 'true' else False
        ticker = secrets['ticker'].upper()

        tstamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        workdir = os.path.join(shared_dir,ticker)
        os.makedirs(workdir,exist_ok=True)

        csv_file = os.path.join(workdir,f'gex-{tstamp}.csv')
        json_file = os.path.join(workdir,f'spot-{tstamp}.json')
        session = Session(username,password,is_test=is_test)
        asyncio.run(cache_gex_csv(session,ticker,csv_file,json_file,expiration_count=1))
        #coro = cache_gex_csv(session,ticker,csv_file,json_file,expiration_count=1)
        #future = asyncio.ensure_future(coro)
        message = {"json_found":os.path.exists(json_file),"csv_found":os.path.exists(csv_file),"tstamp":tstamp}
        return jsonify(message), 200
    except:
        return jsonify({"message":traceback.format_exc()}),400

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("port",type=int)
    args = parser.parse_args()
    app.run(debug=True,host="0.0.0.0",port=args.port)

