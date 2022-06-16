#region imports
from hashlib import new
from AlgorithmImports import *
import enum
#endregion

class LiquidateState(enum.Enum):
    Normal = 1 # It is not mandatory to liquidate.
    ToWin = 2  # It is mandatory to liquidate if there is a win or there is not a loss. Equity current price >= entry price.
    Force = 3  # Liquidate the equity now.

class VWAP(QCAlgorithm):

    def Initialize(self):
        #Region - Initialize cash flow
        self.SetStartDate(2021, 1, 1)   # Set Start Date.
        self.SetEndDate(2021, 1, 31)    # Set End Date.
        self.SetCash(100000)            # Set Strategy Cash.

        self.stocksTrading = QCStocksTrading(self)
        
        # Region - Initialize trading equities
        ## One equity should be traded at least.
        equity1 = self.AddEquity("spy", Resolution.Second)
        self.stocksTrading.AddEquity(equity1)

        # Region - Set Broker configurations
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        
        # Region - General configurations
        # All the variables that manages times are written in seconds.
        self.ConsolidateSecondsTime = 60        # Define the one min candle.
        self.ConsolidateLowPriceTime = 60 * 5   # Define low price candle, used on vwap strategy.
        self.AccumulatePositiveTimeRan = 0      # Interval time when all equity price should be over the vwap before entering in a buy trade.
        
        self.IsAllowToTradeByTime = False

        self.CurrentTradingDay = -1

        self.LiquidateState = LiquidateState.Normal

        ## Sub region - Schedule events
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(equity1.Symbol, 5), self.ResetDataAfterMarketOpenHandler)
        self.endTimeToTradeBeforeMarketClose = 0
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equity1.Symbol, self.endTimeToTradeBeforeMarketClose), self.BeforeMarketCloseHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equity1.Symbol, self.endTimeToTradeBeforeMarketClose + 10), self.BeforeMarketCloseTryToLiquidateOnWinStateHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equity1.Symbol, self.endTimeToTradeBeforeMarketClose + 5), self.BeforeMarketCloseLiquidateOnDayStateHandler)
        
        # Risk management
        self.RiskPerTrade = 200

        # Region - Configuration per symbol
        for trading_equity in self.stocksTrading.GetTradingEquities():
            symbol = trading_equity.Symbol()
            # Indicators
            # QuantConnect indicators has a field 'name' which returns the indicator name.
            self.stocksTrading.RegisterIndicatorForEquity(symbol, 'vwap', self.VWAP(symbol))     # Maybe we can test if it is a good fit for us. Example vwap.Name

            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateSecondsTime), self.MinuteConsolidateHandler)
            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateLowPriceTime), self.LowConsolidateHandler)

    def OnData(self, data):
        for trading_equity in self.stocksTrading.GetTradingEquities():
            symbol = trading_equity.Symbol()
            if not data.Bars.ContainsKey(symbol):
                return

            equity_current_price = data.Bars[symbol].Price

            if self.CurrentTradingDay != self.Time.day:
                self.UpdateOpenPriceAfterMarketOpenHandler(trading_equity, equity_current_price)
                self.CurrentTradingDay = self.Time.day

            if self.ShouldIgnoreOnDataEvent(trading_equity, data):
                return

            self.UpdateLastBrokenCandle(trading_equity)

            # Liquidate by time
            if (self.ShouldLiquidateToWin(equity_current_price) 
                or self.ShouldForceLiquidate()):
                self.Liquidate(symbol)
                return

            if not self.LiquidateState is LiquidateState.Normal:
                return

            if (not self.Portfolio[symbol].Invested 
                and self.ShouldEnterToBuy(trading_equity, equity_current_price)):
                    trading_equity.LastEntryPrice = equity_current_price
                    trading_equity.LastEntryLowPrice = self.LowPriceWindow[0].Low
                    count_actions_to_buy = int(self.RiskPerTrade/(trading_equity.LastEntryPrice - trading_equity.LastEntryLowPrice))
                    self.MarketOrder(symbol, count_actions_to_buy)
                    trading_equity.ResetEquityLastTradeTime(self)
            elif self.Portfolio[symbol].Invested:
                if (trading_equity.LastEntryLowPrice > equity_current_price or
                (trading_equity.LastEntryPrice + (trading_equity.LastEntryPrice - trading_equity.LastEntryLowPrice)) < equity_current_price):
                    self.Liquidate(symbol)
                    trading_equity.ResetEquityLastTradeTime(self)

    # Eval when we shouldn't make a trade. This block specify when to trade or not to trade.
    def ShouldIgnoreOnDataEvent(self, trading_equity, data):
        if not trading_equity.IsAllowToTradeByGapPercent:
            return True
        if not self.IsAllowToTradeByTime:
            return True
        vwap = trading_equity.GetIndicator('vwap')
        if ((not vwap is None and
            not vwap.IsReady) or
            not trading_equity.CurrentTradingWindow.IsReady or
            not trading_equity.LowPriceWindow.IsReady):
            return True
        if (self.Time - trading_equity.LastTradeTime).total_seconds() < self.ConsolidateSecondsTime:
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
            equity.CurrentTradingWindow = RollingWindow[TradeBar](2)
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

    # Region Consolidates, update rolling windows
    def MinuteConsolidateHandler(self, bar):
        for equity in self.stocksTrading.GetTradingEquities():
            equity.CurrentTradingWindow.Add(bar)

    def LowConsolidateHandler(self, bar):
        for equity in self.stocksTrading.GetTradingEquities():
            equity.LowPriceWindow.Add(bar)
    # EndRegion

    def ShouldLiquidateToWin(self, equity_current_price):
        if (self.LiquidateState is LiquidateState.ToWin
            and self.Portfolio.Invested
            and self.LastEntryPrice <= equity_current_price):
            return True
        return False

    def ShouldForceLiquidate(self):
        if (self.LiquidateState is LiquidateState.Force
            and self.Portfolio.Invested):
            return True
        return False

    # 1 - Enter to buy when the previous candle High price is greater than VWAP current value  
    #     and its Low price is lower than VWAP current value and the same time
    # 2 - The equity current price is greater than the previous candle high value.
    def ShouldEnterToBuy(self, trading_equity, equity_current_price):
        return (not trading_equity.LastBrokenCandle is None
            and self.IsPositiveBrokenCandle(trading_equity)
            and (trading_equity.CurrentTradingWindow[0].Time - trading_equity.LastBrokenCandle.Time).total_seconds() >= self.AccumulatePositiveTimeRan
            and equity_current_price > self.CurrentTradingWindow[0].High) 
   
    def IsPositiveBrokenCandle(self, trading_equity):
        candle = trading_equity.CurrentTradingWindow[0]
        vwap = trading_equity.GetIndicator('vwap')
        return (not vwap is None 
            and (candle.High > vwap.Current.Value
            and candle.Low < vwap.Current.Value         
            and candle.Close >= vwap.Current.Value))
    
    def UpdateLastBrokenCandle(self, trading_equity):
        current_trading_window = trading_equity.CurrentTradingWindow[0]
        vwap = trading_equity.GetIndicator('vwap')
        if (not vwap is None
            and not trading_equity.LastBrokenCandle is None 
            and current_trading_window.Low < vwap.Current.Value):
            trading_equity.LastBrokenCandle = None
        if (trading_equity.LastBrokenCandle is None
            and self.IsPositiveBrokenCandle(trading_equity)):
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
        self.LastEntryLowPrice = None
        self.LastDayClosePrice = None

        self.LastTradeTime = None

        self.IsAllowToTradeByGapPercent = True
        self.DefaultGapPercentAllowToTrade = default_gap_percent_to_trade

        self.LastBrokenCandle = None
        self.CurrentTradingWindow = None
        self.LowPriceWindow = None

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
        if indicator_name is self.indicators:
            return self.indicators[indicator_name]
        return None
       
class QCEquityTradeModel(EquityTradeModel):
    def __init__(self, equity):
        EquityTradeModel.__init__(self, equity.Symbol, equity)
        
        self.LastBrokenCandle = None
        self.CurrentTradingWindow = RollingWindow[TradeBar](2)
        self.LowPriceWindow = RollingWindow[TradeBar](1)

        def ResetEquityLastTradeTime(self, qc_algorithm):
            self.SetLastTradeTime(qc_algorithm.Time)
            
class StocksTrading:
    def __init__(self):
        self.equities = {}
    
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
        if equity_symbol is self.equities:
            return self.equities[equity_symbol].RegisterIndicator(indicator_name, indicator)
        return False

    # Return True if the indicator was unregistered from the equity
    def UnRegisterIndicatorForEquity(self, equity_symbol, indicator_name):
        if equity_symbol is self.equities:
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
        return  symbol is self.equities

    # Return EquityTradeModel of the parameter 'symbol'
    def GetEquity(self, symbol):
        if self.IsEquityBeingTrading(symbol):
            return self.equities[symbol]
        return None

class QCStocksTrading(StocksTrading):
    def __init__(self, qcAlgorithm):
        StocksTrading.__init__(self)
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
