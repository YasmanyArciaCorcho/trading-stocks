#region imports
from hashlib import new
from locale import DAY_3
from AlgorithmImports import *
import enum
#endregion

class LiquidateState(enum.Enum):
    Normal = 1 # It is not mandatory to liquidate.
    ToWin = 2  # It is mandatory to liquidate if there is a win or there is not a loss. Equity current price >= entry price.
    Force = 3  # Liquidate the equity now.

class TargerPriceStrategy(QCAlgorithm):

    def Initialize(self):
        #Region - Initialize cash flow
        self.SetStartDate(2021, 1, 4)   # Set Start Date.
        self.SetEndDate(2021, 1, 6)    # Set End Date.
        self.SetCash(1000000)            # Set Strategy Cash.
        # The second parameter indicate the number of allowed daily trades per equity
        # By default if the second parameter is not defined there is not limited on the allowed daily trades
        self.stocksTrading = QCStocksTrading(self, -1)

        # Region - Initialize trading equities
        ## One equity should be traded at least.
        equities_symbols = ["qqq"]
        self.equities_prices = []
        day1 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day2 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day3 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day4 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day5 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day6 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day7 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day8 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day9 = [DailyEquityPrice("qqq", 309, 300,350,330)]
        day10 = [DailyEquityPrice("qqq", 309, 300,350,330)]

        self.equities_prices.append(day1)
        self.equities_prices.append(day2)
        self.equities_prices.append(day3)
        self.equities_prices.append(day4)
        self.equities_prices.append(day5)
        self.equities_prices.append(day6)
        self.equities_prices.append(day7)
        self.equities_prices.append(day8)
        self.equities_prices.append(day9)
        self.equities_prices.append(day10)

        self.CurrentDay = 0

        for symbol in equities_symbols:
            equity = self.AddEquity(symbol, Resolution.Second)
            self.stocksTrading.AddEquity(equity)

        # Region - Set Broker configurations
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Margin)
        
        # Region - General configurations
        # All the variables that manages times are written in seconds.
        self.ConsolidateSecondsTime = 60        # Define the one min candle.
        self.ConsolidateLowPriceTime = 60   # Define low price candle, used on vwap strategy.
        self.AccumulatePositiveTimeRan = 0     # Interval time when all equity price should be over the vwap before entering in a buy trade.
        
        # Define time between trades with the same equity.
        # example if we buy we can sell or buy again after 60 seconds if
        # TimeBetweenTrades is 60.
        self.TimeBetweenTrades = 60
        
        self.IsTradeAllowed = True
        # if IsAllowToTradeByTime we can do trades.
        self.IsAllowToTradeByTime = False

        self.CurrentTradingDay = -1

        self.LiquidateState = LiquidateState.Normal

        ## Sub region - Schedule events
        ### AfterMarketOpen and BeforeMarketClose (x, time) is based on mins.
        # Reset initial configurations to do the daily trades.
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.AfterMarketOpen(equities_symbols[0], 0), self.ResetDataAfterMarketOpenHandler)
        # after SetDisallowedOnBuyHandler runs just sell trades are allowed
        self.Schedule.On(self.DateRules.EveryDay(), self.TimeRules.BeforeMarketClose(equities_symbols[0], 10), self.SetDisallowedOnBuyHandler)
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

            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateSecondsTime), self.CurrentTradingWindowConsolidateHandler)
            self.Consolidate(symbol, timedelta(seconds=self.ConsolidateLowPriceTime), self.LowConsolidateHandler)
        
        self.Strategies = [BuyTargetPriceStrategyAction(), SellTargetPriceStrategyAction()]
        self.StrategiesEntriesId = {}
        # self.Strategy = BuyTargetPriceStrategyAction()
        # self.Strategy = SellTargetPriceStrategyAction()

    def OnData(self, data):
        if self.CurrentDay >= len(self.equities_prices):
            return

        for trading_equity in self.stocksTrading.GetTradingEquities():
            symbol = trading_equity.Symbol()
            if not data.Bars.ContainsKey(symbol):
                continue

            equity_current_price = data.Bars[symbol].Price

            if self.CurrentTradingDay != self.Time.day:
                self.UpdateOpenPriceAfterMarketOpenHandler(trading_equity, equity_current_price)
                self.stocksTrading.ResetDailyTradeRegister()
                self.CurrentTradingDay = self.Time.day

            if self.ShouldIgnoreOnDataEvent(trading_equity):
                continue

            # Liquidate by time
            if (self.ShouldLiquidateToWin(trading_equity, equity_current_price) 
                or self.ShouldForceLiquidate(symbol)):
                self.LiquidateCurrentEquityTrade(symbol)
                continue

            if not self.IsOnTradeAllowedState():
               continue

            self.TryToUpdateStopOrderPrice(trading_equity, equity_current_price)

            allow_to_trade = self.stocksTrading.IsAllowToBuyByTradesPerDayCapacity(symbol)
            for strategy in self.Strategies:
                if (symbol in self.StrategiesEntriesId.keys()
                    and self.StrategiesEntriesId[symbol] == strategy):
                    continue

                if (allow_to_trade
                    and strategy.ShouldEnterToBuy(self, trading_equity.Symbol(), equity_current_price)):
                    strategy.SetTradingEquityBuyPriceData(self, trading_equity, equity_current_price)
                    if trading_equity.StopOrderUpdatePriceByRish == 0:
                        continue
                    count_actions_to_buy = int(self.RiskPerTrade / trading_equity.StopOrderUpdatePriceByRish)
                    self.StrategiesEntriesId[symbol] = strategy
                    ticket = strategy.PerformOrder(self, symbol, count_actions_to_buy)
                    trading_equity.SetLastTradeTime(self.Time)
                    self.stocksTrading.RegisterEntryOrder(symbol)
                    trading_equity.LasEntryOrderId = ticket.OrderId
                    strategy.AddStopLose(self, trading_equity, count_actions_to_buy, equity_current_price)
                    break

    def GetCurrentEquityPrice(self, symbol):
        current_day_data = self.equities_prices[self.CurrentDay]
        for equity_price in current_day_data:
            if equity_price.EquitySimbol == symbol:
                return equity_price
        return None

    def LT4nugoGMykWR1yxePXsdUVNKbuinFn6Dj(self, equity_symbol):
        self.Liquidate(equity_symbol)

    def ResetEquityTradePrice(self, trading_equity):
        trading_equity.LastEntryPrice = None
        trading_equity.LastStopEntryPrice = None
        trading_equity.StopOrderUpdatePriceByRish = None
        trading_equity.LastExitOrder = None

    # Eval when we shouldn't make a trade. This block specify when to trade or not to trade.
    def ShouldIgnoreOnDataEvent(self, trading_equity):
        if not trading_equity.IsAllowToTradeByGapPercent:
            return True
        if not self.IsAllowToTradeByTime:
            return True
        if (not trading_equity.CurrentTradingWindow.IsReady or
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
        self.IsTradeAllowed = True
        self.IsAllowToTradeByTime = True
        self.LiquidateState = LiquidateState.Normal
        self.StrategiesEntriesId = {}
        self.CurrentDay = self.CurrentDay + 1
        for equity in self.stocksTrading.GetTradingEquities():
            equity.CurrentTradingWindow = RollingWindow[TradeBar](1)
            equity.LowPriceWindow = RollingWindow[TradeBar](1)
    # EndRegion

    def SetDisallowedOnBuyHandler(self):
        self.IsTradeAllowed = False

    # Region - Before market close.
    def BeforeMarketCloseHandler(self):
        self.IsTradeAllowed = False
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
            and not trading_equity.LastEntryPrice is None 
            and trading_equity.LastEntryPrice >= equity_current_price):
            return True
        return False

    def ShouldForceLiquidate(self, symbol):
        if (self.LiquidateState is LiquidateState.Force
            and self.Portfolio[symbol].Invested):
            return True
        return False

    def  IsOnTradeAllowedState(self):
        return self.IsTradeAllowed
   
    def CalculateMarketGapPercent(self, last_close_day_price, CurrentDay_open_price):
        return (CurrentDay_open_price - last_close_day_price) / CurrentDay_open_price * 100

    def TryToUpdateStopOrderPrice(self, trading_equity, equity_current_price):
        for strategy in self.Strategies:
            strategy.TryToUpdateStopOrderPrice(trading_equity, equity_current_price)
        
    def OnOrderEvent(self, orderEvent):
     if (orderEvent.Status == OrderStatus.Filled
         or orderEvent.Status == OrderStatus.Canceled):
            trading_equity = self.stocksTrading.GetEquity(orderEvent.Symbol)
            if (not trading_equity is None
                and not trading_equity.LastExitOrder is None
                and trading_equity.LastExitOrder.OrderId == orderEvent.OrderId):
                trading_equity.LastExitOrder = None
                self.StrategiesEntriesId[orderEvent.Symbol] = None
                if orderEvent.Status == OrderStatus.Filled:
                    trading_equity.SetLastTradeTime(self.Time)

class TargetPriceStrategyAction:
    def __init__(self):
        pass

    def TryToUpdateStopOrderPrice(self, trading_equity, equity_current_price):
        pass

    def ShouldEnterToBuy(self, algo, trading_equity, equity_current_price):
        pass

    def SetTradingEquityBuyPriceData(self, algo, trading_equity, equity_current_price):
        pass

    def PerformOrder(self, algo, symbol, quantity):
        pass

    # def OnOrderEvent(self, algo, orderEvent):
    #     pass

    def AddStopLose(self, algo, trading_equity, quantity, equity_current_price):
        pass

class BuyTargetPriceStrategyAction(TargetPriceStrategyAction):
    def TryToUpdateStopOrderPrice(self, trading_equity, equity_current_price):
        if trading_equity.LastExitOrder is None:
            return
        if (not trading_equity.LastExitOrder.Status is OrderStatus.Filled
            and equity_current_price - trading_equity.LastEntryPrice > trading_equity.StopOrderUpdatePriceByRish):
            current_stop_price = trading_equity.LastEntryPrice + trading_equity.StopOrderUpdatePriceByRish/2
            trading_equity.LastEntryPrice = trading_equity.LastEntryPrice + trading_equity.StopOrderUpdatePriceByRish
            update_settings = UpdateOrderFields()
            update_settings.StopPrice = current_stop_price
            update_settings.LimitPrice = current_stop_price  - 0.05
            trading_equity.LastExitOrder.Update(update_settings)
        
    def ShouldEnterToBuy(self, algo, trading_equity_symbol, equity_current_price):
        equity_price_data = algo.GetCurrentEquityPrice(trading_equity_symbol)
        if (not equity_price_data is None):
            return equity_current_price >= equity_price_data.BuyEntryPriceLow and equity_current_price <= equity_price_data.BuyEntryPriceHigh
        return False

    def SetTradingEquityBuyPriceData(self, algo, trading_equity, equity_current_price):
        trading_equity.LastEntryPrice = equity_current_price
        equity_daily_price = algo.GetCurrentEquityPrice(trading_equity.Symbol())
        trading_equity.LastStopEntryPrice = equity_daily_price.BuyEntryPriceLow 
        trading_equity.StopOrderUpdatePriceByRish = abs(trading_equity.LastEntryPrice - trading_equity.LastStopEntryPrice)
    
    def PerformOrder(self, algo, symbol, quantity):
        return algo.MarketOrder(symbol, quantity)
    
    # def OnOrderEvent(self, algo, orderEvent):
    #     if (orderEvent.Status == OrderStatus.Filled):
    #         trading_equity = algo.stocksTrading.GetEquity(orderEvent.Symbol)
    #         if (not trading_equity is None
    #             and trading_equity.LastExitOrder is None):
    #            self.SetTradingEquityBuyPriceData(trading_equity, orderEvent.FillPrice)
    #            ticket = algo.StopLimitOrder(orderEvent.Symbol, -orderEvent.Quantity, trading_equity.LastStopEntryPrice, trading_equity.LastStopEntryPrice - 0.5)
    #            trading_equity.LastExitOrder = ticket.OrderId
    #            trading_equity.LasEntryOrderId = None
    #         elif(not trading_equity.LastExitOrder is None
    #             and trading_equity.LastExitOrder == orderEvent.OrderId):
    #             algo.ResetEquityTradePrice(trading_equity)
    #         trading_equity.SetLastTradeTime(algo.Time)

    def AddStopLose(self, algo, trading_equity, quantity, equity_current_price):
        self.SetTradingEquityBuyPriceData(algo, trading_equity, equity_current_price)
        trading_equity.LastExitOrder = algo.StopLimitOrder(trading_equity.Symbol(), -quantity, trading_equity.LastStopEntryPrice, trading_equity.LastStopEntryPrice - 0.5)

class SellTargetPriceStrategyAction(TargetPriceStrategyAction):
    def TryToUpdateStopOrderPrice(self, trading_equity, equity_current_price):
        if trading_equity.LastExitOrder is None:
            return
        if (not trading_equity.LastExitOrder.Status is OrderStatus.Filled
            and trading_equity.LastEntryPrice - equity_current_price > trading_equity.StopOrderUpdatePriceByRish):
            current_stop_price = trading_equity.LastEntryPrice - trading_equity.StopOrderUpdatePriceByRish/2
            trading_equity.LastEntryPrice = trading_equity.LastEntryPrice - trading_equity.StopOrderUpdatePriceByRish
            update_settings = UpdateOrderFields()
            update_settings.StopPrice = current_stop_price
            update_settings.LimitPrice = current_stop_price + 0.05
            trading_equity.LastExitOrder.Update(update_settings)
        
    def ShouldEnterToBuy(self, algo, trading_equity_symbol, equity_current_price):
        equity_price_data = algo.GetCurrentEquityPrice(trading_equity_symbol)
        if (not equity_price_data is None):
            return equity_current_price >= equity_price_data.SellEntryPriceLow and equity_current_price <= equity_price_data.SellEntryPriceHigh
        return False

    def SetTradingEquityBuyPriceData(self, algo, trading_equity, equity_current_price):
        trading_equity.LastEntryPrice = equity_current_price
        equity_daily_price = algo.GetCurrentEquityPrice(trading_equity.Symbol())
        trading_equity.LastStopEntryPrice =  equity_daily_price.SellEntryPriceHigh
        trading_equity.StopOrderUpdatePriceByRish = abs(trading_equity.LastEntryPrice - trading_equity.LastStopEntryPrice)
    
    def PerformOrder(self, algo, symbol, quantity):
        return algo.Sell(symbol, quantity)
    
    # def OnOrderEvent(self, algo, orderEvent):
    #     if (orderEvent.Status == OrderStatus.Filled):
    #         trading_equity = algo.stocksTrading.GetEquity(orderEvent.Symbol)
    #         if (not trading_equity is None
    #             and trading_equity.LastExitOrder is None):
    #            self.SetTradingEquityBuyPriceData(trading_equity, orderEvent.FillPrice)
    #            ticket = algo.StopLimitOrder(orderEvent.Symbol, -orderEvent.Quantity, trading_equity.LastStopEntryPrice, trading_equity.LastStopEntryPrice + 0.5)
    #            trading_equity.LastExitOrder = ticket.OrderId
    #            trading_equity.LasEntryOrderId = None
    #         elif(not trading_equity.LastExitOrder is None
    #             and trading_equity.LastExitOrder == orderEvent.OrderId):
    #             algo.ResetEquityTradePrice(trading_equity)
    #         trading_equity.SetLastTradeTime(algo.Time)

    def AddStopLose(self, algo, trading_equity, quantity, equity_current_price):
        self.SetTradingEquityBuyPriceData(algo, trading_equity, equity_current_price)
        trading_equity.LastExitOrder = algo.StopLimitOrder(trading_equity.Symbol(), quantity, trading_equity.LastStopEntryPrice, trading_equity.LastStopEntryPrice + 0.5)

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

        self.LasEntryOrderId = None
        self.LastExitOrder = None

        self.LastTradeTime = None

        self.IsAllowToTradeByGapPercent = True
        self.DefaultGapPercentAllowToTrade = default_gap_percent_to_trade

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

    def RegisterEntryOrder(self, symbol):
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

class DailyEquityPrice:
    def __init__(self, equity_simbol, buy_entry_price_high, buy_entry_price_low, sell_entry_price_high, sell_entry_price_low):
        self.EquitySimbol = equity_simbol
        self.BuyEntryPriceHigh = buy_entry_price_high
        self.BuyEntryPriceLow = buy_entry_price_low
        self.SellEntryPriceHigh = sell_entry_price_high
        self.SellEntryPriceLow = sell_entry_price_low