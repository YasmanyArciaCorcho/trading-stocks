import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd


def PlotCandles(json_candles):
    df = pd.json_normalize(json_candles['candles'])
    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # include candlestick with range selector
    fig.add_trace(go.Candlestick(x=df['datetime'],
                                 open=df['open'], high=df['high'],
                                 low=df['low'], close=df['close']),
                  secondary_y=True)

    # include a go.Bar trace for volumes
    fig.add_trace(go.Bar(x=df['datetime'], y=df['volume']),
                  secondary_y=False)

    fig.layout.yaxis2.showgrid = False
    fig.show()
