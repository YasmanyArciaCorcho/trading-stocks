#region imports
from AlgorithmImports import *
import enum
#endregion

class LiquidateState(enum.Enum):
    Normal = 1 # 'It is not mandatory to liquidate'
    ToWin = 2  # 'It is mandatory to liquidate if there is a win or there is not a loss. Equity current price >= entry price' 
    Force = 3  # 'Liquidate the equity now'

class VWAP(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2021, 1, 1)   # Set Start Date
        self.SetEndDate(2021, 1, 31)    # Set End Date
        self.SetCash(100000)            # Set Strategy Cash

        self.stocksTrading = QCStocksTrading(self)
        
        # we should be trading at least 1 equity
        equity1 = self.AddEquity("spy", Resolution.Second)

        self.stocksTrading.AddEquity(equity1.Symbol, equity1)

        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        
        # General configurations
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(equity1.Symbol, 5), self.ResetDataAfterMarketOpenHandler)
        
        self.endTimeToTradeBeforeMarketClose = 0
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equity1.Symbol, self.endTimeToTradeBeforeMarketClose), self.BeforeMarketCloseHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equity1.Symbol, self.endTimeToTradeBeforeMarketClose + 10), self.BeforeMarketCloseTryToLiquidateOnWinStateHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equity1.Symbol, self.endTimeToTradeBeforeMarketClose + 5), self.BeforeMarketCloseLiquidateOnDayStateHandler)

        # All the variables that manages times are written in seconds.
        self.consolidateSecondsTime = 60
        self.accumulatePositiveTimeRan = 0
        self.consolidateLowPriceTime = 60 * 5
        
        self.isAllowToTradeByTime = False

        self.currentTradeDay = -1

        self.LiquidateState = LiquidateState.Normal
        
        # Risk management
        self.risk_per_trade = 200

        # configuration per symbol
        # strategy per symbol
        for symbol in self.stocksTrading.GetEquitiesTradingSymbols():
            # Indicators
            vwap = self.VWAP(symbol)                                        # The indicator has a field 'name' which returns the indicator name.
            self.stocksTrading.RegisterIndicatorForEquity('vwap', vwap)     # Maybe we can test if it is a good fit for us. Example vwap.Name
           
            self.lastBrokenCandle = None
            self.tradingWindows = RollingWindow[TradeBar](2)
            self.Consolidate(symbol, timedelta(seconds=self.consolidateSecondsTime), self.MinuteConsolidateHandler)
    
            self.windowLowPrice = RollingWindow[TradeBar](1)
            self.Consolidate(symbol, timedelta(seconds=self.consolidateLowPriceTime), self.LowConsolidateHandler)

    def OnData(self, data):
        for symbol in self.stocksTrading.GetEquitiesTradingSymbols():
            if not data.Bars.ContainsKey(symbol):
                return

            trading_equity = self.stocksTrading.GetEquity(symbol)
            equity_current_price = data.Bars[symbol].Price

            if self.currentTradeDay != self.Time.day:
                self.UpdateOpenPriceAfterMarketOpenHandler(trading_equity, equity_current_price)
                self.currentTradeDay = self.Time.day

            if self.ShouldIgnoreOnDataEvent(trading_equity, data):
                return

            self.UpdateLastBrokenCandle(self.tradingWindows[0])

            # Liquidate by time
            if (self.ShouldLiquidateToWin(equity_current_price) 
                or self.ShouldForceLiquidate()):
                self.Liquidate(symbol)
                return

            if not self.LiquidateState is LiquidateState.Normal:
                return

            if not self.Portfolio[symbol].Invested and self.ShouldEnterToBuy(equity_current_price):
                    trading_equity.LastEntryPrice = equity_current_price
                    trading_equity.LastEntryLowPrice = self.windowLowPrice[0].Low
                    count_actions_to_buy = int(self.risk_per_trade/(trading_equity.LastEntryPrice - trading_equity.LastEntryLowPrice))
                    self.MarketOrder(symbol, count_actions_to_buy)
                    self.stocksTrading.ResetEquityLastTradeTime(symbol)
            elif self.Portfolio[symbol].Invested:
                if (trading_equity.LastEntryLowPrice > equity_current_price or
                (trading_equity.LastEntryPrice + (trading_equity.LastEntryPrice - trading_equity.LastEntryLowPrice)) < equity_current_price):
                    self.stocksTrading.ResetEquityLastTradeTime(symbol)
                    self.Liquidate(symbol)

    # Eval when we shouldn't make a trade. This block specify when to trade or not to trade.
    def ShouldIgnoreOnDataEvent(self, trading_equity, data):
        if not trading_equity.IsAllowToTradeByGapPercent:
            return True
        if not self.isAllowToTradeByTime:
            return True
        if (not trading_equity['vwap'].IsReady or
            not self.tradingWindows.IsReady or
            not self.windowLowPrice.IsReady):
            return True
        if (self.Time - trading_equity.LastTradeTime).total_seconds() < self.consolidateSecondsTime:
            return True
        return False

    def UpdateOpenPriceAfterMarketOpenHandler(self, trading_equity, equity_open_day_price):
        if trading_equity.LastDayClosePrice is None:
            return
        gapPercent = self.CalculateMarketGapPercent(trading_equity.LastDayClosePrice, equity_open_day_price)
        trading_equity.IsAllowToTradeByGapPercent = gapPercent > trading_equity.DefaultGapPercentAllowToTrade # add percent per gap. if gapPercent < 2 => means if gap percent is less than 2 percent.

    def ResetDataAfterMarketOpenHandler(self):
        self.isAllowToTradeByTime = True
        self.tradingWindows = RollingWindow[TradeBar](2)
        self.LiquidateState = LiquidateState.Normal

    def BeforeMarketCloseHandler(self):
        self.isAllowToTradeByTime = False
        for equity in self.stocksTrading.GetEquitiesTradingEquities():
            equity.LastDayClosePrice = self.Securities["SPY"].Price

    def BeforeMarketCloseTryToLiquidateOnWinStateHandler(self):
        self.LiquidateState = LiquidateState.ToWin

    def BeforeMarketCloseLiquidateOnDayStateHandler(self):
        self.LiquidateState = LiquidateState.Force

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
    def ShouldEnterToBuy(self, price):
        return (not self.lastBrokenCandle is None
            and self.IsPositiveBrokenCandle(self.tradingWindows[0])
            and (self.tradingWindows[0].Time - self.lastBrokenCandle.Time).total_seconds() >= self.accumulatePositiveTimeRan
            and price > self.tradingWindows[0].High) 
   
    def IsPositiveBrokenCandle(self, candle):
        return (candle.High > self.vwap.Current.Value
            and candle.Low < self.vwap.Current.Value         
            and candle.Close >= self.vwap.Current.Value)
    
    def UpdateLastBrokenCandle(self, bar):
        if (not self.lastBrokenCandle is None 
            and bar.Low < self.vwap.Current.Value):
            self.lastBrokenCandle = None
        if (self.lastBrokenCandle is None
            and self.IsPositiveBrokenCandle(bar)):
            self.lastBrokenCandle = bar
        
    # Update the rolling windows with the current consolidate.
    def MinuteConsolidateHandler(self, bar):
        self.tradingWindows.Add(bar)

    def LowConsolidateHandler(self, bar):
        self.windowLowPrice.Add(bar)

    def CalculateMarketGapPercent(self, last_close_day_price, current_day_open_price):
        return (current_day_open_price - last_close_day_price)/current_day_open_price*100

# So far, all prices are based in USD dollar for any field. 
# self.LastEntryPrice = 1 <=> self.LastEntryPrice = 1 USD

class EquityTradeModel:
    def __init__(self, symbol, equity, default_gap_percent_to_trade = 0):
        self.__symbol = symbol
        self.__equity = equity

        self.__indicators = {}

        self.LastEntryPrice = None
        self.LastEntryLowPrice = None
        self.LastDayClosePrice = None

        self.LastTradeTime = None

        self.IsAllowToTradeByGapPercent = True
        self.DefaultGapPercentAllowToTrade = default_gap_percent_to_trade

    def Symbol(self):
        return self.__symbol

    def Equity(self):
        return self.__equity

    # Return True if the indicator registered
    def RegisterIndicator(self, indicator_name, indicator):
        if not indicator_name in self.__indicators:
            self.__indicators[indicator_name] = indicator
            return True
        return False
    
    # Return True if the indicator unregistered
    def UnRegisterIndicator(self, indicator_name):
        if indicator_name in self.__indicators:
            del self.__indicators[indicator_name]
            return True
        return False

    def SetLastTradeTime(self, time):
        self.LastTradeTime = time
    
class QCEquityTradeModel(EquityTradeModel):
    def __init__(self, equity, data_normalization_mode):
        self.super().__init__(equity.Symbol)
        
        equity.SetDataNormalizationMode(data_normalization_mode)
        self.SetBenchmark(self.Symbol())
    
class StocksTrading:
    def __init__(self):
        self.__equities = {}
    
    # return True if the equity was added correctly.
    def AddEquity(self, equity_symbol, equity):
        if equity_symbol is self.__equitie:
            return False
        self.__equities[equity_symbol] = EquityTradeModel(equity_symbol, equity)
        return True

    # Return True if the equity was removed correctly.
    def RemoveEquity(self, equity_symbol):
        del self.__equities[equity_symbol]

    # Return True if the indicator was registered for the equity
    def RegisterIndicatorForEquity(self, equity_symbol, indicator_name, indicator):
        if equity_symbol is self.__equities:
            return self.__equities[equity_symbol].RegisterIndicator(indicator_name, indicator)
        return False

    # Return True if the indicator was unregistered from the equity
    def UnRegisterIndicatorForEquity(self, equity_symbol, indicator_name):
        if equity_symbol is self.__equities:
            return self.__equities[equity_symbol].UnRegisterIndicator(indicator_name)
        return False

    # Return the list of symbols that currently are being trading
    def GetEquitiesTradingSymbols(self):
        return self.__equities.keys()

    def GetEquitiesTradingEquities(self):
        return self.__equities.values()

    # Return amount of trading.
    def TotalStocksBeingTrading(self):
        return len(self.__equities)

    def IsEquityBeingTrading(self, symbol):
        return  symbol is self.__equities

    # Return EquityTradeModel of the parameter 'symbol'
    def GetEquity(self, symbol):
        if self.IsEquityBeingTrading(symbol):
            return self.__equities[symbol]
        return None

class QCStocksTrading(StocksTrading):
    def __init__(self, qcAlgorithm):
        super().__init__()
        self.__qcAlgorithm = qcAlgorithm
    
    def AddEquity(self, equity_symbol, equity):
        if equity_symbol is self.__equitie:
            return False
        equity.SetDataNormalizationMode(DataNormalizationMode.Raw)

        qc_equity_model = self.__equities[equity_symbol] = QCEquityTradeModel(equity_symbol, equity)
        qc_equity_model.LastTradeTime = self.__qcAlgorithm.Time

    def RegisterIndicatorForEquity(self, indicator):
        super().AddIndicatorForEquity(indicator.Name, indicator)

    def ResetEquityLastTradeTime(self, symbol):
        if self.IsEquityBeingTrading(symbol):
            self.__equitie[symbol].SetLastTradeTime(self.__qcAlgorithm.Time)
