#region imports
from AlgorithmImports import *
#endregion
class VWAP(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2021, 9, 18)  # Set Start Date
        self.SetEndDate(2021, 9, 23) # Set End Date
        self.SetCash(100000)  # Set Strategy Cash
        
        spy = self.AddEquity("spy", Resolution.Second)
        spy.SetDataNormalizationMode(DataNormalizationMode.Raw)
        self.spy = spy.Symbol
        
        self.SetBenchmark(self.spy)
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(self.spy, 5), self.AfterMarketOpenHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(self.spy, 0), self.BeforeMarketCloseHandler)

        # Indicators
        self.vwap = self.VWAP(self.spy)
        
        self.isValidTradeTime = False

        # Price are based in USD dollar. 
        # self.entryPrice = 1 <=> self.entryPrice = 1 USD
        self.entryPrice = 0
        self.currentDayOpenPrice = 0
        self.lastDayClosePrice = 0

        # All the variables that manages times are written in seconds.
        self.consolidateSecondsTime = 60
        self.accumulatePositiveTimeRan = 0
        self.lastTrade = self.Time
        self.consolidateLowPriceTime = 60 * 5

        # self.defaultAllowMarketGapPercentToTrade = -1 => 1% <=> gap down
        self.defaultAllowMarketGapPercentToTrade = -1

        self.lastBrokenCandle = None
        self.windowMinute = RollingWindow[TradeBar](2)
        self.Consolidate(self.spy, timedelta(seconds=self.consolidateSecondsTime), self.MinuteConsolidateHandler)

        self.windowLowPrice = RollingWindow[TradeBar](1)
        self.Consolidate(self.spy, timedelta(seconds=self.consolidateLowPriceTime), self.LowConsolidateHandler)

    def OnData(self, data):
        if self.currentDayOpenPrice is 0:
            self.currentDayOpenPrice = data.Bars[self.spy].Price

        if self.ShouldSkipOnDataEvent(data):
            return

        price = data.Bars[self.spy].Close

        self.UpdateLastBrokenCandle(self.windowMinute[0])

        # self.Log("V" + str(self.vwap.Current.Value)) # Current VWAP vaule
        # price = data[self.spy].Close
        # price = self.Securities[self.spy].Close
        if not self.Portfolio.Invested and self.ShouldEnterToBuy(price):
                self.SetHoldings(self.spy, 1)
                self.entryPrice = price
                self.ResetLastTradeTime()
                self.entryLowPrice = self.windowLowPrice[0].Low
        elif self.Portfolio.Invested:
            if (self.entryLowPrice > price or
            (self.entryPrice + (self.entryPrice - self.entryLowPrice)) < price):
                self.Liquidate()
                self.ResetLastTradeTime()

    # Eval when we shouldn't make a trade. This block specify when to trade or not to trade.
    def ShouldSkipOnDataEvent(self, data):
        if not self.isValidTradeTime:
            return True
        if self.lastDayClosePrice is 0:
            return True
        if (not self.vwap.IsReady or
            not self.windowMinute.IsReady or
            not self.windowLowPrice.IsReady):
            return True
        if not self.spy in data:
            return True
        if (self.Time - self.lastTrade).total_seconds() < self.consolidateSecondsTime:
            return True
        if (not self.lastDayClosePrice is 0
            and not self.currentDayOpenPrice is 0):
            gapPercent = self.CalcualteMarketGapPercent(self.lastDayClosePrice, self.currentDayOpenPrice)
            if gapPercent < self.defaultAllowMarketGapPercentToTrade: # add percent per gap. if gapPercent < 2 => means if gap percent is less than 2 percent.
                self.Log(gapPercent)
                return True
        return False

    def AfterMarketOpenHandler(self):
        self.isValidTradeTime = True
        self.windowMinute = RollingWindow[TradeBar](2)

    def BeforeMarketCloseHandler(self):
        self.isValidTradeTime = False
        self.lastDayClosePrice = self.windowMinute[0].Close
        self.currentDayOpenPrice = 0

    # 1 - Enter to buy when the previous candle High price is greater than VWAP current value  
    #     and its Low price is lower than VWAP current value and the same time
    # 2 - The equity current price is greater than the previous candle high value.
    def ShouldEnterToBuy(self, price):
        return (not self.lastBrokenCandle is None
            and self.IsPositiveBrokenCandle(self.windowMinute[0])
            and (self.windowMinute[0].Time - self.lastBrokenCandle.Time).total_seconds() >= self.accumulatePositiveTimeRan
            and price > self.windowMinute[0].High) 
   
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
        self.windowMinute.Add(bar)

    def LowConsolidateHandler(self, bar):
        self.windowLowPrice.Add(bar)

    def ResetLastTradeTime(self):
        self.lastTrade = self.Time

    def CalcualteMarketGapPercent(self, lastCloseDayPrice, currentDayOpenPrice):
        return (currentDayOpenPrice - lastCloseDayPrice)/currentDayOpenPrice*100