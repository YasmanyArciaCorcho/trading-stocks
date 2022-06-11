import json
import authentication as auth
from tda import client
import plot_candles


auth_client = auth.GetAuthClient()

r = auth_client.get_price_history('AAPL',
        period_type=client.Client.PriceHistory.PeriodType.DAY,
        period=client.Client.PriceHistory.Period.ONE_DAY,
        # frequency_type=client.Client.PriceHistory.FrequencyType.DAILY,
        frequency=client.Client.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES)
assert r.status_code == 200, r.raise_for_status()
price_history = r.json()
plot_candles.PlotCandles(price_history)
