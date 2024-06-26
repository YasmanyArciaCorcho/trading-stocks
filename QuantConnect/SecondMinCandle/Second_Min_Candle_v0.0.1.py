#region imports
from hashlib import new
from AlgorithmImports import *
import enum
#endregion

class LiquidateState(enum.Enum):
    Normal = 1 # It is not mandatory to liquidate.
    ToWin = 2  # It is mandatory to liquidate if there is a win or there is not a loss. Equity current price >= entry price.
    Force = 3  # Liquidate the equity now.

class VWAPStrategy(QCAlgorithm):

    def Initialize(self):
        #Region - Initialize cash flow
        self.SetStartDate(2021, 1, 5)   # Set Start Date.
        self.SetEndDate(2021, 1, 8)    # Set End Date.
        self.SetCash(1000000)            # Set Strategy Cash.

        # The second parameter indicate the number of allowed daily trades per equity
        # By default if the second parameter is not defined there is not limited on the allowed daily trades
        self.stocksTrading = QCStocksTrading(self, 1)

        # Region - Initialize trading equities
        ## One equity should be traded at least.
        equities_symbols = ["aapl", "spy", "tsla", "msft", "ba", "qqq", "fb", "pypl", "twtr", "nvda", "amd", "c", "baba", "bac", "gld", "tgt", "wmt", "amzn", "googl"]

        for symbol in equities_symbols:
            equity = self.AddEquity(symbol, Resolution.Second)
            self.stocksTrading.AddEquity(equity)

        # Region - Set Broker configurations
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        
        # Region - General configurations
        # All the variables that manages times are written in seconds.
        self.ConsolidateSecondsTime = 60        # Define the one min candle.
        self.ConsolidateLowPriceTime = 60       # Define low price candle, used on vwap strategy.
        self.AccumulatePositiveTimeRan = 0      # Interval time when all equity price should be over the vwap before entering in a buy trade.
        
        self.IsAllowToTradeByTime = False

        self.CurrentTradingDay = -1

        self.LiquidateState = LiquidateState.Normal

        ## Sub region - Schedule events
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(equities_symbols[0], 0), self.ResetDataAfterMarketOpenHandler)
        self.endTimeToTradeBeforeMarketClose = 0
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.At(4, 00), self.PassSecondMinHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equities_symbols[0], self.endTimeToTradeBeforeMarketClose + 10), self.BeforeMarketCloseTryToLiquidateOnWinStateHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equities_symbols[0], self.endTimeToTradeBeforeMarketClose + 5), self.BeforeMarketCloseLiquidateOnDayStateHandler)
        # Risk management
        self.RiskPerTrade = 200

        # Region - Configuration per symbol
        for trading_equity in self.stocksTrading.GetTradingEquities():
            symbol = trading_equity.Symbol()
            # Indicators
            # QuantConnect indicators has a field 'name' which returns the indicator name.
            self.stocksTrading.RegisterIndicatorForEquity(symbol, 'vwap', self.VWAP(symbol)) # Maybe we can test if it is a good fit for us. Example vwap.Name

            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateSecondsTime), self.CurrentTradingWindowConsolidateHandler)
            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateLowPriceTime), self.LowConsolidateHandler)

    def OnData(self, data):
        for trading_equity in self.stocksTrading.GetTradingEquities():
            symbol = trading_equity.Symbol()
            if not data.Bars.ContainsKey(symbol):
                continue

            equity_current_price = data.Bars[symbol].Price

            if self.CurrentTradingDay != self.Time.day:
                self.stocksTrading.ResetDailyTradeRegister()
                self.CurrentTradingDay = self.Time.day

            if self.ShouldIgnoreOnDataEvent(trading_equity, data):
                continue

            if (not self.IsAllowToTradeByTime
                and not trading_equity.LastTicket is None
                and not trading_equity.LastTicket.Status == OrderStatus.Filled):
                trading_equity.LastTicket.Cancel()
                trading_equity.LastTicket = None

            # Liquidate by time
            if (self.ShouldLiquidateToWin(trading_equity, equity_current_price) 
                or self.ShouldForceLiquidate(symbol)):
                self.Liquidate(symbol)
                continue

            if (#not self.Portfolio[symbol].Invested
                not trading_equity.Invested
                and self.stocksTrading.IsAllowToBuyByTradesPerDayCapacity(symbol)
                and self.ShouldEnterToBuy(trading_equity, equity_current_price)):
                    trading_equity.Invested = True
                    self.Log(str(trading_equity.Invested))
                    trading_equity.LastEntryPrice = equity_current_price
                    trading_equity.LastEntryExitOnLostPrice = min(trading_equity.LowPriceWindow[0].Low, trading_equity.CurrentTradingWindow[0].Low)
                    trading_equity.LastEntryExitOnWinPrice = trading_equity.LastEntryPrice + (trading_equity.LastEntryPrice - trading_equity.LastEntryExitOnLostPrice) * 2
                    denominator = trading_equity.LastEntryPrice - trading_equity.LastEntryExitOnLostPrice
                    if denominator == 0:
                        continue
                    count_actions_to_buy = int(self.RiskPerTrade / denominator)
                    #self.MarketOrder(symbol, count_actions_to_buy)
                    trading_equity.LastTicket = self.LimitOrder(symbol, count_actions_to_buy, trading_equity.LastEntryPrice + 0.01)
                    trading_equity.SetLastTradeTime(self.Time)
                    self.stocksTrading.RegisterBuyOrder(symbol)
            # self.Portfolio[symbol].Invested:
            elif trading_equity.Invested:
                if (trading_equity.LastEntryExitOnLostPrice > equity_current_price or
                    trading_equity.LastEntryExitOnWinPrice <= equity_current_price):
                    trading_equity.Invested = False
                    self.Liquidate(symbol)
                    trading_equity.SetLastTradeTime(self.Time)

    # Eval when we shouldn't make a trade. This block specify when to trade or not to trade.
    def ShouldIgnoreOnDataEvent(self, trading_equity, data):
            if (not trading_equity.CurrentTradingWindow.IsReady or
            not trading_equity.LowPriceWindow.IsReady):
                return True
            return False    

    def UpdateOpenPriceAfterMarketOpenHandler(self, trading_equity, equity_open_day_price):
        if trading_equity.LastDayClosePrice is None:
            return
        gapPercent = self.CalculateMarketGapPercent(trading_equity.LastDayClosePrice, equity_open_day_price)
        trading_equity.IsAllowToTradeByGapPercent = gapPercent > trading_equity.DefaultGapPercentAllowToTrade # add percent per gap. if gapPercent < 2 => means if gap percent is less than 2 percent.

    # Region After Market Open
    def ResetDataAfterMarketOpenHandler(self):
        self.IsAllowToTradeByTime = True
        self.LiquidateState = LiquidateState.Normal
        for equity in self.stocksTrading.GetTradingEquities():
            equity.FirstCandle = None
            equity.CurrentTradingWindow = RollingWindow[TradeBar](1)
            equity.LowPriceWindow = RollingWindow[TradeBar](1)
    # EndRegion

    # Region - Before market close.
    def BeforeMarketCloseHandler(self):
        self.IsAllowToTradeByTime = False
        for equity in self.stocksTrading.GetTradingEquities():
            equity.LastDayClosePrice = self.Securities[equity.Symbol()].Price

    def BeforeMarketCloseTryToLiquidateOnWinStateHandler(self):
        self.LiquidateState = LiquidateState.ToWin

    def BeforeMarketCloseLiquidateOnDayStateHandler(self):
        self.LiquidateState = LiquidateState.Force
    # EndRegion

    def PassSecondMinHandler(self):
        self.IsAllowToTradeByTime = False

    # Region Consolidates, update rolling windows
    def CurrentTradingWindowConsolidateHandler(self, trade_bar):
        equity = self.stocksTrading.GetEquity(trade_bar.Symbol)
        if not equity is None:
            equity.CurrentTradingWindow.Add(trade_bar)
            if equity.FirstCandle is None:
                equity.FirstCandle = trade_bar

    def LowConsolidateHandler(self, trade_bar):
        equity = self.stocksTrading.GetEquity(trade_bar.Symbol)
        if not equity is None:
            equity.LowPriceWindow.Add(trade_bar)
    # EndRegion

    def ShouldLiquidateToWin(self, trading_equity, equity_current_price):
        if (self.LiquidateState is LiquidateState.ToWin
            and self.Portfolio[trading_equity.Symbol()].Invested
            and trading_equity.LastEntryPrice <= equity_current_price):
            return True
        return False

    def ShouldForceLiquidate(self, symbol):
        if (self.LiquidateState is LiquidateState.Force
            and self.Portfolio[symbol].Invested):
            return True
        return False

    # 1 - Enter to buy when the previous candle High price is greater than VWAP current value  
    #     and its Low price is lower than VWAP current value and the same time
    # 2 - The equity current price is greater than the previous candle high value.
    def ShouldEnterToBuy(self, trading_equity, equity_current_price):
        return (self.IsAllowToTradeByTime
                and equity_current_price > trading_equity.FirstCandle.High)

    def IsPositiveBrokenCandle(self, vwap, trading_equity):
        candle = trading_equity.CurrentTradingWindow[0]
        return (not vwap is None 
            and (candle.Low < vwap.Current.Value         
            and candle.Close >= vwap.Current.Value))
    
    def UpdateLastBrokenCandle(self, trading_equity):
        current_trading_window = trading_equity.CurrentTradingWindow[0]
        vwap = trading_equity.GetIndicator('vwap')
        if vwap is None:
            return
        if (not trading_equity.LastBrokenCandle is None 
            and current_trading_window.Low < vwap.Current.Value
            and current_trading_window.Close < vwap.Current.Value):
            trading_equity.LastBrokenCandle = None
            return
        if (trading_equity.LastBrokenCandle is None
            and self.IsPositiveBrokenCandle(vwap, trading_equity)):
            trading_equity.LastBrokenCandle = current_trading_window

    def CalculateMarketGapPercent(self, last_close_day_price, current_day_open_price):
        return (current_day_open_price - last_close_day_price) / current_day_open_price * 100

# So far, all prices are based in USD dollar for any field. 
# self.LastEntryPrice = 1 <=> self.LastEntryPrice = 1 USD

class EquityTradeModel:
    def __init__(self, symbol, equity, default_gap_percent_to_trade = 0):
        self.__symbol = symbol
        self.__equity = equity

        self.indicators = {}

        self.LastEntryPrice = None
        self.LastEntryExitOnLostPrice = None
        self.LastEntryExitOnWinPrice = None
        self.LastDayClosePrice = None

        self.LastTradeTime = None

        self.IsAllowToTradeByGapPercent = True
        self.DefaultGapPercentAllowToTrade = default_gap_percent_to_trade

        self.LastBrokenCandle = None
        self.CurrentTradingWindow = None
        self.LowPriceWindow = None
        self.LastTicket = None
        self.Invested = False

    def Symbol(self):
        return self.__symbol

    def Equity(self):
        return self.__equity

    # Return True if the indicator registered
    def RegisterIndicator(self, indicator_name, indicator):
        if not indicator_name in self.indicators:
            self.indicators[indicator_name] = indicator
            return True
        return False
    
    # Return True if the indicator unregistered
    def UnRegisterIndicator(self, indicator_name):
        if indicator_name in self.indicators:
            del self.indicators[indicator_name]
            return True
        return False

    def SetLastTradeTime(self, time):
        self.LastTradeTime = time

    def ResetEquityLastTradeTime(self):
        self.SetLastTradeTime(None)

    def GetIndicator(self, indicator_name):
        if indicator_name in self.indicators:
            return self.indicators[indicator_name]
        return None
       
class QCEquityTradeModel(EquityTradeModel):
    def __init__(self, equity):
        EquityTradeModel.__init__(self, equity.Symbol, equity)
        
        self.LastBrokenCandle = None
        self.CurrentTradingWindow = RollingWindow[TradeBar](1)
        self.LowPriceWindow = RollingWindow[TradeBar](1)
        self.FirstCandle = None

        def ResetEquityLastTradeTime(self, qc_algorithm):
            self.SetLastTradeTime(qc_algorithm.Time)
            
class StocksTrading:
    def __init__(self, max_allowed_trade_per_day = -1):
        self.equities = {}

        self.maxAllowedTradePerDay = max_allowed_trade_per_day
        self.registeredOrders = {}
    
    # return True if the equity was added correctly.
    def AddEquity(self, equity_symbol, equity):
        if equity_symbol is self.__equitie:
            return False
        self.equities[equity_symbol] = EquityTradeModel(equity_symbol, equity)
        return True

    # Return True if the equity was removed correctly.
    def RemoveEquity(self, equity_symbol):
        del self.equities[equity_symbol]

    # Return True if the indicator was registered for the equity
    def RegisterIndicatorForEquity(self, equity_symbol, indicator_name, indicator):
        if equity_symbol in self.equities:
            return self.equities[equity_symbol].RegisterIndicator(indicator_name, indicator)
        return False

    # Return True if the indicator was unregistered from the equity
    def UnRegisterIndicatorForEquity(self, equity_symbol, indicator_name):
        if equity_symbol in self.equities:
            return self.equities[equity_symbol].UnRegisterIndicator(indicator_name)
        return False

    # Return the list of symbols that currently are being trading
    def GetEquitiesTradingSymbols(self):
        return self.equities.keys()

    def GetTradingEquities(self):
        return self.equities.values()

    # Return amount of trading.
    def TotalStocksBeingTrading(self):
        return len(self.equities)

    def IsEquityBeingTrading(self, symbol):
        return symbol in self.equities

    # Return EquityTradeModel of the parameter 'symbol'
    def GetEquity(self, symbol):
        if self.IsEquityBeingTrading(symbol):
            return self.equities[symbol]
        return None

    def RegisterBuyOrder(self, symbol):
        if not symbol in self.registeredOrders:
            self.registeredOrders[symbol] = 1
        self.registeredOrders[symbol] += 1

    def IsAllowToBuyByTradesPerDayCapacity(self, symbol):
        if self.maxAllowedTradePerDay == -1:
            return True
        if not symbol in self.registeredOrders:
            return True
        return self.registeredOrders[symbol] <= self.maxAllowedTradePerDay
    
    def ResetDailyTradeRegister(self):
        self.registeredOrders = {}


class QCStocksTrading(StocksTrading):
    def __init__(self, qcAlgorithm, max_allowed_trade_per_day = -1):
        StocksTrading.__init__(self, max_allowed_trade_per_day)
        self.__qcAlgorithm = qcAlgorithm
    
    def AddEquity(self, equity):
        if not self.GetEquity(equity.Symbol) is None:
            return False

        equity.SetDataNormalizationMode(DataNormalizationMode.Raw)

        qc_equity_model = self.equities[equity.Symbol] = QCEquityTradeModel(equity)
        qc_equity_model.LastTradeTime = self.__qcAlgorithm.Time

    def RegisterIndicatorForEquity(self, equity_symbol, indicator):
        StocksTrading.RegisterIndicatorForEquity(self, equity_symbol, indicator.Name, indicator)

    def RegisterIndicatorForEquity(self, equity_symbol, indicator_name, indicator):
        StocksTrading.RegisterIndicatorForEquity(self, equity_symbol, indicator_name, indicator)