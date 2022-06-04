#region imports
from AlgorithmImports import *
import enum
#endregion

# self.Log("V" + str(self.vwap.Current.Value)) # Current VWAP vaule
 # price = data[self.spy].Close
# price = self.Securities[self.spy].Close
class LiquidateState(enum.Enum):
    Normal = 1 # 'It is not mandatory to liquidate'
    ToWin = 2  # 'It is mandatory to liquidate if there is a win or there is not a loss. Equity current price >= entry price' 
    Force = 3  # 'Liquidate the equity now'

class VWAP(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2021, 1, 1)  # Set Start Date
        self.SetEndDate(2021, 1, 31) # Set End Date
        self.SetCash(100000)  # Set Strategy Cash
        
        spy = self.AddEquity("NFLX", Resolution.Second)
        spy.SetDataNormalizationMode(DataNormalizationMode.Raw)
        self.spy = spy.Symbol
        self.SetBenchmark(self.spy)
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(self.spy, 5), self.ResetDataAfterMarketOpenHandler)
        
        self.endTimeToTradeBeforeMarketClose = 0
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(self.spy, self.endTimeToTradeBeforeMarketClose), self.BeforeMarketCloseHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(self.spy, self.endTimeToTradeBeforeMarketClose + 10), self.BeforeMarketCloseTryToLiquidateOnWinStateHandler)
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(self.spy, self.endTimeToTradeBeforeMarketClose + 5), self.BeforeMarketCloseLiquidateOnDayStateHandler)

        # Indicators
        self.vwap = self.VWAP(self.spy)
        
        self.isAllowToTradeByTime = False

        # Price are based in USD dollar. 
        # self.entryPrice = 1 <=> self.entryPrice = 1 USD
        self.entryPrice = 0

        # All the variables that manages times are written in seconds.
        self.consolidateSecondsTime = 60
        self.accumulatePositiveTimeRan = 0
        self.lastTrade = self.Time
        self.consolidateLowPriceTime = 60 * 5

        # self.defaultAllowMarketGapPercentToTrade = -1 => 1% <=> gap down
        self.lastDayClosePrice = None
        self.defaultAllowMarketGapPercentToTrade = 0.5
        self.allowGapPercentToTrade = 0
        self.isAllowToTradeByGapPercent = False

        self.currentTradeDay = -1

        self.lastBrokenCandle = None
        self.windowMinute = RollingWindow[TradeBar](2)
        self.Consolidate(self.spy, timedelta(seconds=self.consolidateSecondsTime), self.MinuteConsolidateHandler)

        self.windowLowPrice = RollingWindow[TradeBar](1)
        self.Consolidate(self.spy, timedelta(seconds=self.consolidateLowPriceTime), self.LowConsolidateHandler)

        self.LiquidateState = LiquidateState.Normal

        # Risk management
        self.risk_per_trade = 200

    def OnData(self, data):
        if not data.Bars.ContainsKey(self.spy):
            return

        price = data.Bars[self.spy].Price
        
        if self.currentTradeDay != self.Time.day:
            self.UpdateOpenPriceAfterMarketOpenHandler(price)
            self.currentTradeDay = self.Time.day
        
        if self.ShouldIgnoreOnDataEvent(data):
            return

        self.UpdateLastBrokenCandle(self.windowMinute[0])

        # Liquidate by time
        if (self.ShouldLiquidateToWin(price) 
            or self.ShouldForceLiquidate()):
            self.Liquidate()
            return
        
        if not self.Portfolio.Invested and self.ShouldEnterToBuy(price):
                self.entryPrice = price
                self.entryLowPrice = self.windowLowPrice[0].Low
                count_actions_to_buy = int(self.risk_per_trade/(self.entryPrice - self.entryLowPrice))
                self.MarketOrder(self.spy, count_actions_to_buy)
                self.Log('ep' + str(self.entryPrice))
                self.Log('elp' + str(self.entryLowPrice))
                self.Log('atb'+ str(count_actions_to_buy))
                self.ResetLastTradeTime()
        elif self.Portfolio.Invested:
            if (self.entryLowPrice > price or
            (self.entryPrice + (self.entryPrice - self.entryLowPrice)) < price):
                self.Liquidate()
                self.ResetLastTradeTime()

    # Eval when we shouldn't make a trade. This block specify when to trade or not to trade.
    def ShouldIgnoreOnDataEvent(self, data):
        if not self.isAllowToTradeByGapPercent:
            return True
        if not self.isAllowToTradeByTime:
            return True
        if (not self.vwap.IsReady or
            not self.windowMinute.IsReady or
            not self.windowLowPrice.IsReady):
            return True
        if (self.Time - self.lastTrade).total_seconds() < self.consolidateSecondsTime:
            return True
        return False

    def UpdateOpenPriceAfterMarketOpenHandler(self, openDayPrice):
        if self.lastDayClosePrice is None:
            return
        gapPercent = self.CalculateMarketGapPercent(self.lastDayClosePrice, openDayPrice)
        self.isAllowToTradeByGapPercent = gapPercent > self.defaultAllowMarketGapPercentToTrade # add percent per gap. if gapPercent < 2 => means if gap percent is less than 2 percent.

    def ResetDataAfterMarketOpenHandler(self):
        self.isAllowToTradeByTime = True
        self.windowMinute = RollingWindow[TradeBar](2)
        self.LiquidateState = LiquidateState.Normal

    def BeforeMarketCloseHandler(self):
        self.isAllowToTradeByTime = False
        self.lastDayClosePrice = self.Securities[self.spy].Price

    def BeforeMarketCloseTryToLiquidateOnWinStateHandler(self):
        self.LiquidateState = LiquidateState.ToWin

    def BeforeMarketCloseLiquidateOnDayStateHandler(self):
        self.LiquidateState = LiquidateState.Force

    def ShouldLiquidateToWin(self, equity_current_price):
        if (self.LiquidateState is LiquidateState.ToWin
            and self.Portfolio.Invested
            and self.entryPrice <= equity_current_price):
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

    def CalculateMarketGapPercent(self, lastCloseDayPrice, currentDayOpenPrice):
        return (currentDayOpenPrice - lastCloseDayPrice)/currentDayOpenPrice*100