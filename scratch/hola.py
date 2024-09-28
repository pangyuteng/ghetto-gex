import os
import sys
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MY_LIB_PATH = os.path.join(os.path.dirname(THIS_DIR),"ghetto-gex-live")
sys.path.append(MY_LIB_PATH)

import asyncio
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

class TickerSubscription:
    def __init__(self,ticker,session):
        self.ticker = ticker
        self.loop = asyncio.get_event_loop()
        self.underlying = UnderlyingLivePrices.create(session, ticker)

    def get_events(self,event_name):
        return self.loop.run_until_complete(self.__async_get_events())

    async def __async_get_events(self):
        async with self.wws as echo:
            await echo.send(json.dumps({'ticks_history': 'R_50', 'end': 'latest', 'count': 1}))
            return await echo.receive()

@app.route('/subscribe', methods=['GET'])
def subscribe():
    try:
        ticker = request.args.to_dict()['ticker']
        ticker = ticker.upper()
        susbcription_manager[ticker]={}
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

# 

"""