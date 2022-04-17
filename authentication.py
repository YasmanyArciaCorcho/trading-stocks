import config
from tda import auth


def GetAuthClient():
    try:
        return auth.client_from_token_file(config.token_path, config.api_key)
    except FileNotFoundError:
        from selenium import webdriver
        with webdriver.Chrome() as driver:
            auth_client = auth.client_from_login_flow(
                driver, config.api_key, config.redirect_uri, config.token_path)
            return auth_client
