import os
import sys
import json
import traceback
import logging
import pathlib
import asyncio

# THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# MY_LIB_PATH = os.path.join(os.path.dirname(THIS_DIR),"ghetto-gex-live")
# sys.path.append(MY_LIB_PATH)
from test_async import background_subscribe, get_cancel_file,get_running_file, get_session


from quart import Quart, request,jsonify

session = get_session()

app = Quart = Quart(__name__,
    static_url_path='', 
    static_folder='static',
    template_folder='templates',
)

@app.route('/', methods=['GET'])
async def index():
    return jsonify("ok")

@app.route('/quotes/<ticker>', methods=['GET'])
async def get_quotes(ticker):
    try:
        ticker = ticker.upper()
        return jsonify({})
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/cancel-sub', methods=['GET'])
async def cancel_sub():
    try:
        ticker = request.args.to_dict()['ticker']
        ticker = ticker.upper()
        cancel_file = get_cancel_file(ticker)
        pathlib.Path(cancel_file).touch()
        return jsonify({"message":f"{ticker} canceled"})
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/subscribe', methods=['GET'])
async def subscribe():
    try:
        ticker = request.args.to_dict()['ticker']
        ticker = ticker.upper()
        running_file = get_running_file(ticker)
        cancel_file = get_cancel_file(ticker)
        if os.path.exists(cancel_file):
             os.remove(cancel_file)
        if os.path.exists(running_file):
             return jsonify({"message":"job running alreay"})
        app.add_background_task(background_subscribe,ticker,session)
        return jsonify({"message":ticker})
    except:
        return jsonify({"message":traceback.format_exc()}),400

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    app.run(debug=True,host="0.0.0.0",port=80)


"""
cd ..

docker run -it -u $(id -u):$(id -g) -p 80:80 \
    --env-file .env \
    -v ghetto-gex-live_shared:/shared \
    -v $PWD:/opt/app \
    -w /opt/app pangyuteng/ghetto-gex-live:latest bash

# subscribe

curl localhost/subscribe?ticker=SPX
curl localhost/quotes/SPX

# 

"""