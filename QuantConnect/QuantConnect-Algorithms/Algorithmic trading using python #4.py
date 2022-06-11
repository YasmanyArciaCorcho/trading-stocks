def OnData(self, data):
        if not self.spy in data:
            return
        if self.CurrentSlice.Bars.ContainsKey(self.spy):
            # price = data.Bars[self.spy].Close
            price = data[self.spy].Close
            
            # price = self.Securities[self.spy].Close
            
            if not self.Portfolio.Invested:
                if self.nextEntryTime <= self.Time:
                    self.SetHoldings(self.spy, 1)
                    # self.MarketOrder(self.spy, int(self.Portfolio.Cash / price) )
                    self.Log("BUY SPY @" + str(price))
                    self.entryPrice = price
            
            elif self.entryPrice * 1.1 < price or self.entryPrice * 0.90 > price:
                self.Liquidate()
                self.Log("SELL SPY @" + str(price))
                self.nextEntryTime = self.Time + self.period