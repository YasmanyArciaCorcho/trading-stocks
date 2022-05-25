#region imports
from AlgorithmImports import *
#endregion
class VWAP(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2022, 4, 22)  # Set Start Date
        self.SetEndDate(2022, 5, 30) # Set End Date
        self.SetCash(100000)  # Set Strategy Cash
        
        spy = self.AddEquity("SPY", Resolution.Second)
        # self.AddForex, self.AddFuture...
        
        spy.SetDataNormalizationMode(DataNormalizationMode.Raw)
        
        self.spy = spy.Symbol
        
        self.SetBenchmark("SPY")
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        
        self.current_min = 0;
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(self.spy, 1), self.ResetAlgoState)

        self.entryPrice = 0
        self.period = timedelta(31)
        self.nextEntryTime = self.Time
        
        # VWAP definition
        self.vwap = self.VWAP(self.spy)
        
        self.previous_state = False # true mind positive, above the vwap
        self.current_state = False  # false mind negative, bellow the vwap

    def OnData(self, data):
        if not self.vwap.IsReady:
            return
        
        if not self.spy in data:
            return
        
        price = data.Bars[self.spy].Close
        
        if self.current_min <= 5:
            self.current_min = self.current_min + 1
            
            if self.current_min < 4:
                return
        
            if self.current_min == 4:
                self.previous_state = price > self.vwap.Current.Value
                return
        
            if self.current_min == 5:
                self.current_state = price > self.vwap.Current.Value
        
        if self.current_min >= 6:
            self.UpdateAlgoState(price);
            
        #self.Log("V" + str(self.vwap.Current.Value)) # Current VWAP vaule
        #self.Log("P" + str(price)) # Current SPY price
        #self.Log("-")
        
        # price = data[self.spy].Close
        # price = self.Securities[self.spy].Close
        
        if not self.Portfolio.Invested and self.ShouldEnterToBuy():
            #if self.nextEntryTime <= self.Time:
                self.SetHoldings(self.spy, 1)
                # self.MarketOrder(self.spy, int(self.Portfolio.Cash / price) )
                
                #self.Log("B " + str(price)) # buy SPY
                self.entryPrice = price
                self.lowBar = data.Bars[self.spy].Low
                
        elif self.lowBar is not None:
            if self.lowBar > price or (self.entryPrice + (self.entryPrice - self.lowBar)) > price:
                self.Liquidate()
                #self.Log("S " + str(price)) #sell spy
                self.nextEntryTime = self.Time + self.period
                self.lowBar = None
            
    def UpdateAlgoState(self, current_price):
        self.previous_state = self.current_state
        self.current_state = current_price > self.vwap.Current.Value
        
    def ResetAlgoState(self):
        self.current_min = 1
        
    def ShouldEnterToBuy(self):
        return not self.previous_state and self.current_state
        
        
            

        