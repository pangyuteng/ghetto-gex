import os
import sys
import json
import traceback

import asyncio

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MY_LIB_PATH = os.path.join(os.path.dirname(THIS_DIR),"ghetto-gex-live")
sys.path.append(MY_LIB_PATH)
from data_utils import get_session, UnderlyingLivePrices

from flask import Flask, request,jsonify

app = Flask(__name__,
    static_url_path='', 
    static_folder='static',
    template_folder='templates',
)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
shared_dir = os.environ.get("SHARED_DIR")

@app.route('/', methods=['GET'])
def index():
    return jsonify("ok")

class TickerSubscriptionManager:
    def __init__(self):
        self.session = get_session()
    def __getitem__(self, key):
        return getattr(self, key)
    def __setitem__(self, key, value):
        setattr(self, key, value)

# https://stackoverflow.com/questions/42009202/how-to-call-a-async-function-contained-in-a-class


class AwaitUnderlyingLivePrices:
    def __init__(self,session,ticker):
        self.session = session
        self.ticker = ticker
    async def __aenter__(self):
        self.underlying = await UnderlyingLivePrices.create(self.session, self.ticker)
        return self
    async def __aexit__(self, *args, **kwargs):
        pass
    async def get_quotes(self):
        return self.underlying.quotes
    

class TickerSubscription:
    def __init__(self,ticker,session):
        self.ticker = ticker
        self.session = session
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.underlying = AwaitUnderlyingLivePrices(self.session,self.ticker)

    def get_quotes(self):
        event_name = "quotes"
        return self.loop.run_until_complete(self.__async_get_events(event_name))

    async def __async_get_events(self,event_name):
        async with self.underlying as myobj:
            return await myobj.get_quotes()

manager = TickerSubscriptionManager()

@app.route('/quotes/<ticker>', methods=['GET'])
def get_quotes(ticker):
    try:
        ticker = ticker.upper()
        myobj = manager[ticker]
        quotes = myobj.get_quotes()
        app.logger.info(str(quotes))
        quotes =json.loads(json.dumps(quotes,default=str))
        return jsonify(quotes)
    except:
        return jsonify({"message":traceback.format_exc()}),400

@app.route('/subscribe', methods=['GET'])
def subscribe():
    try:
        ticker = request.args.to_dict()['ticker']
        ticker = ticker.upper()
        ticker_sub = TickerSubscription(ticker,manager.session)
        manager[ticker]=ticker_sub
        return jsonify({"message":ticker})
    except:
        return jsonify({"message":traceback.format_exc()}),400

if __name__ == '__main__':
    app.run(debug=True,host="0.0.0.0",port=80)


"""
cd ..

docker run -it -u $(id -u):$(id -g) -p 80:80 \
    --env-file .env \
    -v ghetto-live-gex_shared:/shared \
    -v $PWD:/opt/app \
    -w /opt/app pangyuteng/ghetto-live-gex:latest bash

# subscribe

curl localhost/subscribe?ticker=SPX
curl localhost/quotes/SPX

# 

"""