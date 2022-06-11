#region imports
from AlgorithmImports import *
#endregion
class VWAP(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2022, 4, 22)  # Set Start Date
        self.SetEndDate(2022, 5, 28) # Set End Date
        self.SetCash(100000)  # Set Strategy Cash
        
        spy = self.AddEquity("aapl", Resolution.Second)
        spy.SetDataNormalizationMode(DataNormalizationMode.Raw)
        self.spy = spy.Symbol
        
        self.SetBenchmark(self.spy)
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(self.spy, 5), self.AfterMarketOpenHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(self.spy, 1), self.BeforeMarketCloseHandler)

        # Indicators
        self.vwap = self.VWAP(self.spy)
        
        self.entryPrice = 0
        self.lastTrade = self.Time
        self.isValidTradeTime = False

        self.window = RollingWindow[TradeBar](2)
        self.Consolidate(self.spy, timedelta(seconds=60), self.MinuteConsolidateHandler)

    def OnData(self, data):
        if self.ShouldSkipOnDataEvent(data):
            return

        price = data.Bars[self.spy].Close

        # self.Log("V" + str(self.vwap.Current.Value)) # Current VWAP vaule
        # price = data[self.spy].Close
        # price = self.Securities[self.spy].Close
        if not self.Portfolio.Invested and self.ShouldEnterToBuy(price):
                self.SetHoldings(self.spy, 1)
                self.entryPrice = price
                self.ResetLastTradeTime()
                self.entryLowPrice = self.window[0].Low
        elif self.Portfolio.Invested:
            if (self.entryLowPrice > price or
            (self.entryPrice + (self.entryPrice - self.entryLowPrice)) < price):
                self.Liquidate()
                self.ResetLastTradeTime()

    # Eval when we shouldn't make a trade. This block specify when to trade or not to trade.
    def ShouldSkipOnDataEvent(self, data):
        if not self.isValidTradeTime:
            return True
        if not self.vwap.IsReady or not self.window.IsReady:
            return True
        if not self.spy in data:
            return True
        if (self.Time - self.lastTrade).total_seconds() < 60:
            return True
        return False

    def AfterMarketOpenHandler(self):
        self.isValidTradeTime = True
        self.window = RollingWindow[TradeBar](2)

    def BeforeMarketCloseHandler(self):
        self.isValidTradeTime = False
   
    # 1 - Enter to buy when the previous candle High price is greater than VWAP current value  
    #     and its Low price is lower than VWAP current value and the same time
    # 2 - The equity current price is greater than the previous candle high value.
    def ShouldEnterToBuy(self, price):
        return (self.window[0].High > self.vwap.Current.Value # 1
        and self.window[0].Low < self.vwap.Current.Value      # 1
        and price > self.window[0].High)                      # 2

    # Update the rolling windows with the current consolidate.
    def MinuteConsolidateHandler(self, bar):
        self.window.Add(bar)

    # 
    def ResetLastTradeTime(self):
        self.lastTrade = self.Time