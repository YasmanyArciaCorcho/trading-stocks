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
        self.SetStartDate(2021, 1, 1)   # Set Start Date.
        self.SetEndDate(2021, 1, 7)    # Set End Date.
        self.SetCash(1000000)            # Set Strategy Cash.

        # The second parameter indicate the number of allowed daily trades per equity
        # By default if the second parameter is not defined there is not limited on the allowed daily trades
        self.stocksTrading = QCStocksTrading(self, -1)

        # Region - Initialize trading equities
        ## One equity should be traded at least.
        equities_symbols = ["spy"]

        for symbol in equities_symbols:
            equity = self.AddEquity(symbol, Resolution.Second)
            self.stocksTrading.AddEquity(equity)

        # Region - Set Broker configurations
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        
        # Region - General configurations
        # All the variables that manages times are written in seconds.
        self.ConsolidateSecondsTime = 60        # Define the one min candle.
        self.ConsolidateLowPriceTime = 60 * 5   # Define low price candle, used on vwap strategy.
        self.AccumulatePositiveTimeRan = 60      # Interval time when all equity price should be over the vwap before entering in a buy trade.
        
        # Define time between trades with the same equity.
        # example if we buy we can sell or buy again after 60 seconds if
        # TimeBetweenTrades is 60.
        self.TimeBetweenTrades = 60
        
        self.IsBuyAllowed = True
        # if IsAllowToTradeByTime we can do trades.
        self.IsAllowToTradeByTime = False

        self.CurrentTradingDay = -1

        self.LiquidateState = LiquidateState.Normal

        ## Sub region - Schedule events
        ### AfterMarketOpen and BeforeMarketClose (x, time) is based on mins.
        # Reset initial configurations to do the daily trades.
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(equities_symbols[0], 5), self.ResetDataAfterMarketOpenHandler)
        # after SetDisallowedOnBuyHandler runs just sell trades are allowed
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equities_symbols[0], 0), self.SetDisallowedOnBuyHandler)
        # Just sell trades are allowed after SetLiquidateOnWinStateHandler runs
        # On liquidate.Win the algo will try to exit just on winning trades.
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equities_symbols[0], 10), self.SetLiquidateOnWinStateHandler)
        # Just sell trades are allowed after SetLiquidateOnForceStateHandler runs
        # All opened trades will be liquidate on liquidate force state.
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equities_symbols[0], 5), self.SetLiquidateOnForceStateHandler)
        # Any trade is allowed after BeforeMarketCloseHandler runs.
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equities_symbols[0], 0), self.BeforeMarketCloseHandler)
        
        # Risk management
        self.RiskPerTrade = 200

        # Region - Configuration per symbol
        for trading_equity in self.stocksTrading.GetTradingEquities():
            symbol = trading_equity.Symbol()
            # Indicators
            # QuantConnect indicators has a field 'name' which returns the indicator name.
            self.stocksTrading.RegisterIndicatorForEquity(symbol, 'vwap', self.VWAP(symbol))     # Maybe we can test if it is a good fit for us. Example vwap.Name

            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateSecondsTime), self.CurrentTradingWindowConsolidateHandler)
            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateLowPriceTime), self.LowConsolidateHandler)

    def OnData(self, data):
        for trading_equity in self.stocksTrading.GetTradingEquities():
            symbol = trading_equity.Symbol()
            if not data.Bars.ContainsKey(symbol):
                continue

            equity_current_price = data.Bars[symbol].Price

            if self.CurrentTradingDay != self.Time.day:
                self.UpdateOpenPriceAfterMarketOpenHandler(trading_equity, equity_current_price)
                self.stocksTrading.ResetDailyTradeRegister()
                self.CurrentTradingDay = self.Time.day

            if self.ShouldIgnoreOnDataEvent(trading_equity, data):
                continue

            self.UpdateLastBrokenCandle(trading_equity)

            # Liquidate by time
            if (self.ShouldLiquidateToWin(trading_equity, equity_current_price) 
                or self.ShouldForceLiquidate(symbol)):
                self.Liquidate(symbol)
                continue

            self.TryToUpdateStopOrderPrice(trading_equity, equity_current_price)

            if (not self.Portfolio[symbol].Invested
                and self.stocksTrading.IsAllowToBuyByTradesPerDayCapacity(symbol)
                and self.ShouldEnterToBuy(trading_equity, equity_current_price)):
                self.SetTradingEquityBuyPriceData(trading_equity, equity_current_price)
                if trading_equity.StopOrderUpdatePriceByRish == 0:
                    continue
                count_actions_to_buy = int(self.RiskPerTrade / trading_equity.StopOrderUpdatePriceByRish)
                ticket = self.MarketOrder(symbol, count_actions_to_buy)
                trading_equity.LastBuyOrderId = ticket.OrderId

    def ResetEquityTradePrice(self, trading_equity):
        trading_equity.LastEntryPrice = None
        trading_equity.LastStopEntryPrice = None
        trading_equity.StopOrderUpdatePriceByRish = None
        trading_equity.LastSellOrderId = None

    def TryToUpdateStopOrderPrice(self, trading_equity, equity_current_price):
        if trading_equity.LastSellOrderId is None:
            return
        ticket = self.Transactions.GetOrderTicket(trading_equity.LastSellOrderId)
        current_stop_price = trading_equity.LastEntryPrice + trading_equity.StopOrderUpdatePriceByRish
        if current_stop_price - equity_current_price < 0.05:
            current_stop_price = current_stop_price + trading_equity.StopOrderUpdatePriceByRish/2
            ticket.UpdateStopPrice(current_stop_price)
            ticket.UpdateLimitPrice(current_stop_price  - 0.05)
        
    def OnOrderEvent(self, orderEvent: OrderEvent) -> None:
        if (orderEvent.Status == OrderStatus.Filled):
            trading_equity = self.stocksTrading.GetEquity(orderEvent.Symbol)
            if (not trading_equity is None
                and trading_equity.LastSellOrderId is None):
               self.SetTradingEquityBuyPriceData(trading_equity, orderEvent.FillPrice)
               ticket = self.StopLimitOrder(orderEvent.Symbol, -orderEvent.Quantity, trading_equity.LastStopEntryPrice, trading_equity.LastStopEntryPrice - 0.05)
               trading_equity.LastSellOrderId = ticket.OrderId
               self.stocksTrading.RegisterBuyOrder(orderEvent.Symbol)
               trading_equity.LastBuyOrderId = None
            elif(not trading_equity.LastSellOrderId is None
                and trading_equity.LastSellOrderId == orderEvent.OrderId):
                self.ResetEquityTradePrice(trading_equity)
            trading_equity.SetLastTradeTime(self.Time)

    def SetTradingEquityBuyPriceData(self, trading_equity, equity_current_price):
        trading_equity.LastEntryPrice = equity_current_price
        trading_equity.LastStopEntryPrice = min(trading_equity.LowPriceWindow[0].Low, trading_equity.CurrentTradingWindow[0].Low)
        trading_equity.StopOrderUpdatePriceByRish = trading_equity.LastEntryPrice - trading_equity.LastStopEntryPrice
                             
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
        if (self.Time - trading_equity.LastTradeTime).total_seconds() < self.TimeBetweenTrades:
            return True
        return False

    def UpdateOpenPriceAfterMarketOpenHandler(self, trading_equity, equity_open_day_price):
        if trading_equity.LastDayClosePrice is None:
            return
        gapPercent = self.CalculateMarketGapPercent(trading_equity.LastDayClosePrice, equity_open_day_price)
        trading_equity.IsAllowToTradeByGapPercent = gapPercent > trading_equity.DefaultGapPercentAllowToTrade # add percent per gap. if gapPercent < 2 => means if gap percent is less than 2 percent.

    # Region After Market Open
    def ResetDataAfterMarketOpenHandler(self):
        self.IsBuyAllowed = True
        self.IsAllowToTradeByTime = True
        self.LiquidateState = LiquidateState.Normal
        for equity in self.stocksTrading.GetTradingEquities():
            equity.CurrentTradingWindow = RollingWindow[TradeBar](1)
            equity.LowPriceWindow = RollingWindow[TradeBar](1)
            equity.LastBrokenCandle = None
    # EndRegion

    def SetDisallowedOnBuyHandler(self):
        self.IsBuyAllowed = False

    # Region - Before market close.
    def BeforeMarketCloseHandler(self):
        self.IsBuyAllowed = False
        self.IsAllowToTradeByTime = False
        for equity in self.stocksTrading.GetTradingEquities():
            equity.LastDayClosePrice = self.Securities[equity.Symbol()].Price
            self.ResetEquityTradePrice(equity)
        openOrders = self.Transactions.GetOpenOrders()
        if len(openOrders)> 0:
            for order in openOrders:
                self.Transactions.CancelOrder(order.Id)

    def SetLiquidateOnWinStateHandler(self):
        self.LiquidateState = LiquidateState.ToWin

    def SetLiquidateOnForceStateHandler(self):
        self.LiquidateState = LiquidateState.Force
    # EndRegion

    # Region Consolidates, update rolling windows
    def CurrentTradingWindowConsolidateHandler(self, trade_bar):
        equity = self.stocksTrading.GetEquity(trade_bar.Symbol)
        if not equity is None:
            equity.CurrentTradingWindow.Add(trade_bar)

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

    def  IsOnBuyAllowedState(self):
        return self.IsBuyAllowed

    # 1 - Enter to buy when the previous candle High price is greater than VWAP current value  
    #     and its Low price is lower than VWAP current value and the same time
    # 2 - The equity current price is greater than the previous candle high value.
    def ShouldEnterToBuy(self, trading_equity, equity_current_price):
        vwap = trading_equity.GetIndicator('vwap')
        return (self.IsOnBuyAllowedState()
                and not trading_equity.LastBrokenCandle is None
                and self.IsPositiveBrokenCandle(vwap, trading_equity)
                and (trading_equity.CurrentTradingWindow[0].Time - trading_equity.LastBrokenCandle.Time).total_seconds() >= self.AccumulatePositiveTimeRan
                and equity_current_price > trading_equity.CurrentTradingWindow[0].High)

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
        self.LastStopEntryPrice = None
        self.StopOrderUpdatePriceByRish = None
        self.LastDayClosePrice = None

        self.LastBuyOrderId = None
        self.LastSellOrderId = None

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
        if indicator_name in self.indicators:
            return self.indicators[indicator_name]
        return None
       
class QCEquityTradeModel(EquityTradeModel):
    def __init__(self, equity):
        EquityTradeModel.__init__(self, equity.Symbol, equity)
        
        self.LastBrokenCandle = None
        self.CurrentTradingWindow = RollingWindow[TradeBar](1)
        self.LowPriceWindow = RollingWindow[TradeBar](1)

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