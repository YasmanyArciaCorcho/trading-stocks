import config
import json
from tda import auth, client

try:
    auth_client = auth.client_from_token_file(config.token_path, config.api_key)
except FileNotFoundError:
    from selenium import webdriver
    with webdriver.Chrome() as driver:
        auth_client = auth.client_from_login_flow(
            driver, config.api_key, config.redirect_uri, config.token_path)

r = auth_client.get_price_history('AAPL',
        period_type=client.Client.PriceHistory.PeriodType.YEAR,
        period=client.Client.PriceHistory.Period.ONE_DAY,
        frequency_type=client.Client.PriceHistory.FrequencyType.DAILY,
        frequency=client.Client.PriceHistory.Frequency.DAILY)
assert r.status_code == 200, r.raise_for_status()
print(json.dumps(r.json(), indent=4))

# r = auth_client.get_accounts()
# assert r.status_code == 200, r.raise_for_status()
# print(json.dumps(r.json(), indent=4))