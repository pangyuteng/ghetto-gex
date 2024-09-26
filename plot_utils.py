import os
import sys
import pathlib
import json
import pandas as pd
import matplotlib.pyplot as plt

from data_utils import get_data_df

shared_dir = os.environ.get("SHARED_DIR")

def get_png_file_paths(ticker):
    workdir = os.path.join(shared_dir,ticker)
    gex_png_file = os.path.join(workdir,'gex.png')
    price_png_file = os.path.join(workdir,'price.png')
    return gex_png_file, price_png_file

def plot_gex(ticker):

    folder_path = os.path.join(shared_dir,ticker)
    gex_png_file, price_png_file = get_png_file_paths(ticker)

    ticker= os.path.basename(folder_path)

    underlying_df, gex_df_list = get_data_df(folder_path)
    spot_price = float(underlying_df.iloc[-1].close)
    underlying_tstamp = str(underlying_df.iloc[-1].tstamp)

    print(underlying_df.shape)
    print(len(gex_df_list))    
    print('spot_price',spot_price)

    plt.figure(figsize=(15,15))
    plt.plot(underlying_df.time,underlying_df.close)
    plt.savefig(price_png_file)
    plt.close()


    df = gex_df_list[-1]

    csv_basename = os.path.basename(df.iloc[-1].csv_file)
    option_tstamp = csv_basename.replace(".csv","").replace("option-chain-","")

    call_df = df[df.contract_type=='C']
    put_df = df[df.contract_type=='P']

    xmin,xmax = spot_price*0.98,spot_price*1.02
    plt.figure(figsize=(15,15))

    plt.subplot(221)
    plt.bar(call_df.strike,call_df.gexCandleDayVolume,color='orange',width=2)
    plt.bar(put_df.strike,put_df.gexCandleDayVolume,color='blue',width=2)
    plt.axvline(spot_price,color='red',linewidth=2,linestyle='--')
    plt.xlim(xmin,xmax)
    plt.grid(True)
    plt.xlabel("Strike")
    plt.ylabel("gexCandleDayVolume")
    plt.title(f'{ticker} {spot_price} spot gex - candleDayVolume {option_tstamp}')
    plt.subplot(222)
    plt.bar(call_df.strike,call_df.gexTradeDayVolume,color='orange',width=2)
    plt.bar(put_df.strike,put_df.gexTradeDayVolume,color='blue',width=2)
    plt.axvline(spot_price,color='red',linewidth=2,linestyle='--')
    plt.xlim(xmin,xmax)
    plt.grid(True)
    plt.xlabel("Strike")
    plt.ylabel("gexTradeDayVolume")
    plt.title(f'{ticker} {spot_price} spot gex - gexTradeDayVolume {option_tstamp}')
    plt.subplot(223)
    plt.bar(call_df.strike,call_df.gexSummaryOpenInterest,color='orange',width=2)
    plt.bar(put_df.strike,put_df.gexSummaryOpenInterest,color='blue',width=2)
    plt.axvline(spot_price,color='red',linewidth=2,linestyle='--')
    plt.xlim(xmin,xmax)
    plt.grid(True)
    plt.xlabel("Strike")
    plt.ylabel("gexSummaryOpenInterest")
    plt.title(f'{ticker} {spot_price} spot gex - gexSummaryOpenInterest {option_tstamp}')
    plt.subplot(224)
    plt.bar(call_df.strike,call_df.gexPrevDayVolume,color='orange',width=2)
    plt.bar(put_df.strike,put_df.gexPrevDayVolume,color='blue',width=2)
    plt.axvline(spot_price,color='red',linewidth=2,linestyle='--')
    plt.xlim(xmin,xmax)
    plt.grid(True)
    plt.xlabel("Strike")
    plt.ylabel("gexPrevDayVolume")
    plt.title(f'{ticker} {spot_price} spot gex - gexPrevDayVolume {option_tstamp}')
    plt.show()

    plt.savefig(gex_png_file)
    plt.close()

    return gex_png_file,price_png_file

if __name__ == "__main__":
    folder_path = sys.argv[1]
    plot_gex(folder_path)