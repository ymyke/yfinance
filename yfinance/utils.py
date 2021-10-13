#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Yahoo! Finance market data downloader (+fix for Pandas Datareader)
# https://github.com/ranaroussi/yfinance
#
# Copyright 2017-2019 Ran Aroussi
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from __future__ import print_function

import requests as _requests
import re as _re
import pandas as _pd
import numpy as _np
import sys as _sys

try:
    import ujson as _json
except ImportError:
    import json as _json


user_agent_headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}


def empty_df(index=[]):
    '''
        The "empty_df" function creates a pandas dataframe with the index being the dates, and columns including open, high, low, close, adj close and volume. 
        It is used to create an empty dataframe that will be filled later on. 
    '''
    empty = _pd.DataFrame(index=index, data={
        'Open': _np.nan, 'High': _np.nan, 'Low': _np.nan,
        'Close': _np.nan, 'Adj Close': _np.nan, 'Volume': _np.nan})
    empty.index.name = 'Date'
    return empty


def get_html(url, proxy=None, session=None):
    '''
        url: the website you want to visit.
        proxy: a dictionary of your proxies, like {'http': 'http://127.0.0.1:1080', 'https': 'https://127.0.0.1:1080'}
        session: if you have already opened a session with your proxies, then pass it in here.
    '''
    session = session or _requests
    html = session.get(url=url, proxies=proxy, headers=user_agent_headers).text
    return html


def get_json(url: str, proxy: dict = None, session=None):
    '''
        url: the website we want to get json from
        proxy: the proxies that we use to avoid being detected as a robot by websites. 
               It is a dictionary, e.g., {"http":"http://10.10.1.10:3128"}
        session: requests library's object used for sending requests and receiving responses in multiple threads or asynchronous applications

        The function will return a dictionary of data if it works well, otherwise an empty dictionary.
    '''

    session = session or _requests
    html = session.get(url=url, proxies=proxy, headers=user_agent_headers).text

    if "QuoteSummaryStore" not in html:
        html = session.get(url=url, proxies=proxy).text
        if "QuoteSummaryStore" not in html:
            return {}

    json_str = html.split('root.App.main =')[1].split(
        '(this)')[0].split(';\n}')[0].strip()
    data = _json.loads(json_str)[
        'context']['dispatcher']['stores']['QuoteSummaryStore']

    # return data
    new_data = _json.dumps(data).replace('{}', 'null')
    new_data = _re.sub(
        r'\{[\'|\"]raw[\'|\"]:(.*?),(.*?)\}', r'\1', new_data)

    return _json.loads(new_data)


def camel2title(o):
    return [_re.sub("([a-z])([A-Z])", r"\g<1> \g<2>", i).title() for i in o]


def auto_adjust(data):
    '''
        The "auto_adjust" function is used to adjust the dataframe according to the adjusted close price. 
        It takes in a dataframe as an argument and returns a new dataframe with adjusted prices for all columns except volume.
    '''
    df = data.copy()
    ratio = df["Close"] / df["Adj Close"]
    df["Adj Open"] = df["Open"] / ratio
    df["Adj High"] = df["High"] / ratio
    df["Adj Low"] = df["Low"] / ratio

    df.drop(
        ["Open", "High", "Low", "Close"],
        axis=1, inplace=True)

    df.rename(columns={
        "Adj Open": "Open", "Adj High": "High",
        "Adj Low": "Low", "Adj Close": "Close"
    }, inplace=True)

    df = df[["Open", "High", "Low", "Close", "Volume"]]
    return df[["Open", "High", "Low", "Close", "Volume"]]


def back_adjust(data):
    '''
        The function takes in a dataframe as an input and returns the same dataframe with adjusted columns for "Open", "High", "Low" and "Close". 
        The ratio of each adjusted column is calculated by dividing the original Adj Close price by the Close price. 
        Each adjusted column is then multiplied by this ratio to get the new value for that column, which will be used in future calculations.
    '''

    df = data.copy()
    ratio = df["Adj Close"] / df["Close"]
    df["Adj Open"] = df["Open"] * ratio
    df["Adj High"] = df["High"] * ratio
    df["Adj Low"] = df["Low"] * ratio

    df.drop(
        ["Open", "High", "Low", "Adj Close"],
        axis=1, inplace=True)

    df.rename(columns={
        "Adj Open": "Open", "Adj High": "High",
        "Adj Low": "Low"
    }, inplace=True)

    return df[["Open", "High", "Low", "Close", "Volume"]]


def parse_quotes(data, tz=None):
    '''
        The function takes in the data from the "get_data" function and parses it into a pandas DataFrame.
        It uses the timestamps to index each row of data, with the OHLC, volume, and adjusted close all contained within one DataFrame.
        If no timezone is specified for this function then it will default to UTC. 
    '''

    timestamps = data["timestamp"]
    ohlc = data["indicators"]["quote"][0]
    volumes = ohlc["volume"]
    opens = ohlc["open"]
    closes = ohlc["close"]
    lows = ohlc["low"]
    highs = ohlc["high"]

    adjclose = closes
    if "adjclose" in data["indicators"]:
        adjclose = data["indicators"]["adjclose"][0]["adjclose"]

    quotes = _pd.DataFrame({"Open": opens,
                            "High": highs,
                            "Low": lows,
                            "Close": closes,
                            "Adj Close": adjclose,
                            "Volume": volumes})

    quotes.index = _pd.to_datetime(timestamps, unit="s")
    quotes.sort_index(inplace=True)

    if tz is not None:
        quotes.index = quotes.index.tz_localize(tz)

    return quotes


def parse_actions(data, tz=None):
    '''
        The function takes in the data from "get_data" and then checks if there are any events (dividends or splits)
        If so, it creates a pandas DataFrame for each type of event with the date as an index and uses the values as columns
        It also converts all of the dates to datetime objects and sets them as timezone aware if a timezone was specified
    '''
    dividends = _pd.DataFrame(columns=["Dividends"])
    splits = _pd.DataFrame(columns=["Stock Splits"])

    if "events" in data:
        if "dividends" in data["events"]:
            dividends = _pd.DataFrame(
                data=list(data["events"]["dividends"].values()))
            dividends.set_index("date", inplace=True)
            dividends.index = _pd.to_datetime(dividends.index, unit="s")
            dividends.sort_index(inplace=True)
            if tz is not None:
                dividends.index = dividends.index.tz_localize(tz)

            dividends.columns = ["Dividends"]

        if "splits" in data["events"]:
            splits = _pd.DataFrame(
                data=list(data["events"]["splits"].values()))
            splits.set_index("date", inplace=True)
            splits.index = _pd.to_datetime(splits.index, unit="s")
            splits.sort_index(inplace=True)
            if tz is not None:
                splits.index = splits.index.tz_localize(tz)
            splits["Stock Splits"] = splits["numerator"] / \
                splits["denominator"]
            splits = splits["Stock Splits"]

    return dividends, splits


class ProgressBar:
    def __init__(self, iterations, text='completed'):
        '''
            The "__init__" function is the constructor for the class.
            It takes in the parameters that were passed into the class and stores them in variables.
        '''
        self.text = text
        self.iterations = iterations
        self.prog_bar = '[]'
        self.fill_char = '*'
        self.width = 50
        self.__update_amount(0)
        self.elapsed = 1

    def completed(self):
        """
            The "completed" function is a function that is called when the program is completed.
            It prints out the progress bar and then ends the program.
        """
        if self.elapsed > self.iterations:
            self.elapsed = self.iterations
        self.update_iteration(1)
        print('\r' + str(self), end='')
        _sys.stdout.flush()
        print()

    def animate(self, iteration=None):
        '''
            The "animate" function is a function that is called to update the progress bar.
            It takes in an optional parameter, "iteration".
            If "iteration" is not passed in, then the function will increment the "elapsed" variable by 1.
            If "iteration" is passed in, then the function will increment the "elapsed" variable by the value of "iteration".
        '''
        if iteration is None:
            self.elapsed += 1
            iteration = self.elapsed
        else:
            self.elapsed += iteration

        print('\r' + str(self), end='')
        _sys.stdout.flush()
        self.update_iteration()

    def update_iteration(self, val=None):
        '''
            The "update_iteration" function is a function that is called to update the progress bar.
            It takes in an optional parameter, "val".
            If "val" is not passed in, then the function will set the "elapsed" variable to the value of the "iterations" variable.
            If "val" is passed in, then the function will set the "elapsed" variable to the value of "val".
        '''
        val = val if val is not None else self.elapsed / float(self.iterations)
        self.__update_amount(val * 100.0)
        self.prog_bar += '  %s of %s %s' % (
            self.elapsed, self.iterations, self.text)

    def __update_amount(self, new_amount):
        '''    
            The "__update_amount" function is a function that is called to update the progress bar.
            It takes in one parameter, "new_amount".
            It calculates the percentage that the program has completed and stores it in a variable called "percent_done".
            It calculates how many hashes are needed and stores it in a variable called "all_full".
            It calculates how many hashes need to be displayed and stores it in a variable called "num_hashes".
            It creates a string called "pct_string" that displays the percentage that the program has completed.
            It creates a string called "prog_bar" that displays the progress bar.
            It creates a string called "pct_place" that stores where the percentage string should be displayed.
            It returns the value of "prog_bar".
        '''
        percent_done = int(round((new_amount / 100.0) * 100.0))
        all_full = self.width - 2
        num_hashes = int(round((percent_done / 100.0) * all_full))
        self.prog_bar = '[' + self.fill_char * \
            num_hashes + ' ' * (all_full - num_hashes) + ']'
        pct_place = (len(self.prog_bar) // 2) - len(str(percent_done))
        pct_string = '%d%%' % percent_done
        self.prog_bar = self.prog_bar[0:pct_place] + \
            (pct_string + self.prog_bar[pct_place + len(pct_string):])

    def __str__(self):
        '''
            The "__str__" function is a function that is called to return the value of the progress bar.
            It returns the value of "prog_bar".
        '''
        return str(self.prog_bar)
