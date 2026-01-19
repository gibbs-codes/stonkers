# Algorithmic Trading Strategy Catalog

A comprehensive reference of common trading strategies for your algo trading bot. Each strategy includes the core logic, parameters to tune, market conditions where it works, and common failure modes.

---

## Understanding Strategy Categories

| Category | Core Idea | Best Markets | Risk Profile |
|----------|-----------|--------------|--------------|
| **Trend Following** | "The trend is your friend" - ride momentum | Strong directional moves | Larger wins, more losses, lower win rate |
| **Mean Reversion** | "What goes up must come down" - fade extremes | Ranging/choppy markets | Smaller wins, higher win rate, but catastrophic when wrong |
| **Breakout** | Trade the start of new moves | After consolidation periods | High reward when right, many false signals |
| **Momentum** | Strong price action continues | Volatile markets | Quick trades, requires fast execution |

---

## Strategy 1: EMA Crossover (Trend Following)

### The Idea
When a faster-moving average crosses above a slower one, momentum is shifting bullish. The opposite signals bearish momentum.

### Logic
```
LONG:  Fast EMA crosses ABOVE Slow EMA
SHORT: Fast EMA crosses BELOW Slow EMA
EXIT:  Opposite crossover occurs
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `fast_ema` | 9 | 5-20 | Shorter = more signals, more noise |
| `slow_ema` | 21 | 20-50 | Longer = smoother, fewer signals |
| `timeframe` | 15m | 5m-4h | Shorter = more trades, more noise |

### Common Variations
- **Triple EMA**: Add a third EMA (e.g., 9/21/55) - only trade when all three align
- **EMA + Trend Filter**: Only take longs when price > 200 EMA (macro uptrend)

### When It Works
✅ Strong trending markets with clear directional moves  
✅ Markets with momentum that carries through  
✅ Lower timeframes during high-volatility sessions

### When It Fails
❌ Choppy, sideways markets (constant whipsaws)  
❌ News-driven reversals (EMA lags behind)  
❌ Low liquidity periods (false signals)

### Realistic Expectations
- Win rate: 35-45%
- Relies on big winners to offset frequent small losses
- Expect many false signals in ranging markets

---

## Strategy 2: RSI Mean Reversion

### The Idea
RSI (Relative Strength Index) measures if price has moved "too far, too fast." Extreme readings often precede reversals.

### Logic
```
LONG:  RSI crosses ABOVE oversold level (e.g., 30)
SHORT: RSI crosses BELOW overbought level (e.g., 70)
EXIT:  RSI reaches neutral zone (50) or opposite extreme
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `rsi_period` | 14 | 7-21 | Shorter = more sensitive |
| `oversold` | 30 | 20-35 | Lower = fewer but stronger signals |
| `overbought` | 70 | 65-80 | Higher = fewer but stronger signals |
| `neutral_zone` | 45-55 | 40-60 | Exit target range |

### Common Variations
- **RSI + Support/Resistance**: Only take signals at key price levels
- **RSI Smoothed**: Apply EMA to RSI for fewer false signals
- **Multi-timeframe**: Confirm with higher timeframe RSI direction

### When It Works
✅ Range-bound markets with clear support/resistance  
✅ Mean-reverting assets (many crypto pairs in consolidation)  
✅ After extended moves that are likely to retrace

### When It Fails
❌ Strong trends (RSI can stay overbought/oversold for weeks)  
❌ Momentum breakouts (catching a falling knife)  
❌ News events that create sustained directional moves

### Realistic Expectations
- Win rate: 55-65%
- Smaller average wins
- Risk of catastrophic losses if trend continues against you
- REQUIRES strict stop losses

---

## Strategy 3: EMA + RSI Confluence (Your Original Concept)

### The Idea
Combine trend context (EMA) with momentum extreme (RSI) for higher-probability entries.

### Logic
```
LONG:  Price < EMA (below trend) AND RSI crosses above oversold
       "Price is below average AND momentum is turning up"
       
SHORT: Price > EMA (above trend) AND RSI crosses below overbought
       "Price is above average AND momentum is turning down"
       
EXIT:  RSI reaches neutral OR price crosses EMA
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `ema_period` | 100 | 50-200 | The "average" to measure against |
| `rsi_period` | 14 | 7-21 | Momentum measurement |
| `rsi_oversold` | 30 | 25-35 | Entry threshold |
| `rsi_overbought` | 70 | 65-75 | Entry threshold |

### Why This Is Better Than Pure RSI
The EMA filter prevents you from:
- Buying into a strong downtrend (price far below EMA = avoid)
- Shorting into a strong uptrend (price far above EMA = avoid)

### Enhancement Ideas
- Add distance filter: Only trade when price is within X% of EMA
- Add volume confirmation: Higher volume on reversal signals
- Add higher timeframe trend alignment

### When It Works
✅ Markets that oscillate around a moving average  
✅ Pullbacks in trending markets  
✅ Pairs with natural mean-reverting behavior

### When It Fails
❌ Runaway trends (price never returns to EMA)  
❌ Trending markets where "oversold" keeps getting more oversold  
❌ Gap events that bypass your entry levels

### Realistic Expectations
- Win rate: 50-60%
- Fewer trades than pure RSI (more filtered)
- Better risk/reward than pure mean reversion

---

## Strategy 4: Bollinger Band Squeeze

### The Idea
Bollinger Bands measure volatility. When bands contract (squeeze), a big move is coming. Trade the breakout.

### Logic
```
DETECT SQUEEZE: Band width < threshold (volatility compressed)

LONG:  After squeeze, price closes above upper band
SHORT: After squeeze, price closes below lower band
EXIT:  Price returns inside bands OR opposite band touch
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `bb_period` | 20 | 15-25 | Lookback for average/std dev |
| `bb_std` | 2.0 | 1.5-2.5 | Band width multiplier |
| `squeeze_threshold` | 0.04 | 0.03-0.06 | % bandwidth that defines "squeeze" |
| `breakout_candles` | 2 | 1-3 | Candles above band to confirm |

### How to Calculate Squeeze
```python
bandwidth = (upper_band - lower_band) / middle_band
is_squeeze = bandwidth < threshold
```

### When It Works
✅ Markets transitioning from consolidation to trend  
✅ Before major news events (volatility buildup)  
✅ Technical breakouts from patterns (triangles, wedges)

### When It Fails
❌ Choppy markets with no follow-through  
❌ False breakouts (very common in crypto)  
❌ Low-liquidity periods with random wicks

### Realistic Expectations
- Win rate: 40-50%
- Many false breakouts will stop you out
- Winners can be large if you catch real moves
- Consider waiting for breakout confirmation (retest)

---

## Strategy 5: MACD Divergence

### The Idea
When price makes a new high/low but MACD doesn't confirm, momentum is weakening. A reversal may follow.

### Logic
```
BULLISH DIVERGENCE (buy signal):
  - Price makes LOWER low
  - MACD histogram makes HIGHER low
  - Momentum is secretly strengthening
  
BEARISH DIVERGENCE (sell signal):
  - Price makes HIGHER high
  - MACD histogram makes LOWER high
  - Momentum is secretly weakening

EXIT: MACD crosses in signal direction OR fixed target
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `fast_period` | 12 | 8-15 | Fast EMA for MACD |
| `slow_period` | 26 | 20-30 | Slow EMA for MACD |
| `signal_period` | 9 | 7-12 | Signal line smoothing |
| `divergence_lookback` | 10 | 5-20 | Candles to find divergence |

### Enhancement Ideas
- Require price to be at support/resistance
- Combine with RSI divergence for confirmation
- Use higher timeframe MACD for trend direction

### When It Works
✅ Mature trends showing exhaustion  
✅ Clear swing highs/lows to compare  
✅ Markets that respect technical patterns

### When It Fails
❌ Strong trends can show divergence for weeks before reversing  
❌ Divergence is subjective (how far back to look?)  
❌ Crypto often ignores divergence during hype cycles

### Realistic Expectations
- Win rate: 45-55%
- Signals are infrequent but can be high quality
- Requires patience and discipline
- Many "divergences" don't lead to reversals

---

## Strategy 6: Support/Resistance Breakout

### The Idea
Price levels that have been tested multiple times are significant. When they break, the move can be powerful.

### Logic
```
IDENTIFY LEVELS:
  - Resistance: Price rejected from same area 2+ times
  - Support: Price bounced from same area 2+ times

LONG:  Price closes above resistance with volume
SHORT: Price closes below support with volume

EXIT:  Previous support becomes resistance (or vice versa)
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `lookback_period` | 100 | 50-200 | Candles to find levels |
| `level_tolerance` | 0.5% | 0.3-1.0% | How close prices cluster |
| `min_touches` | 2 | 2-4 | Minimum tests of level |
| `volume_multiplier` | 1.5 | 1.2-2.0 | Volume vs average for confirmation |
| `confirmation_candles` | 2 | 1-3 | Closes beyond level |

### Level Detection Approaches
1. **Pivot points**: Mathematical calculation from previous candles
2. **Fractal highs/lows**: Local maxima/minima
3. **Volume profile**: Price levels with most trading activity
4. **Round numbers**: Psychological levels (e.g., $50,000 BTC)

### When It Works
✅ Well-defined trading ranges with clear levels  
✅ High-volume breakouts with follow-through  
✅ Markets that respect technical structure

### When It Fails
❌ False breakouts are extremely common  
❌ Stop hunts (price breaks level then reverses)  
❌ Identifying "real" levels is subjective

### Realistic Expectations
- Win rate: 35-45%
- Many false breakouts
- Requires good level identification
- Consider waiting for retest of broken level

---

## Strategy 7: Volume-Weighted Momentum

### The Idea
Price moves on high volume are more significant than price moves on low volume. Trade with the "smart money."

### Logic
```
VOLUME SPIKE: Current volume > X times average volume

LONG:  Green candle + volume spike + price breaking recent high
SHORT: Red candle + volume spike + price breaking recent low

EXIT:  Volume decreases OR opposite signal
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `volume_ma_period` | 20 | 10-30 | Average volume baseline |
| `volume_threshold` | 2.0 | 1.5-3.0 | Multiplier for "spike" |
| `price_lookback` | 10 | 5-20 | Recent high/low period |
| `hold_candles` | 5 | 3-10 | Minimum hold time |

### When It Works
✅ News-driven moves (volume precedes price)  
✅ Breakouts with institutional participation  
✅ Markets with reliable volume data

### When It Fails
❌ Crypto volume can be unreliable (wash trading)  
❌ Volume spikes at reversals, not just continuations  
❌ Low liquidity pairs have erratic volume

### Realistic Expectations
- Win rate: 40-50%
- Crypto volume data is often suspect
- Works better on major pairs (BTC, ETH)
- Consider combining with other confirmation

---

## Strategy 8: Multi-Timeframe Trend Alignment

### The Idea
Trade in the direction of the higher timeframe trend, enter on lower timeframe signals.

### Logic
```
HIGHER TIMEFRAME (4h/Daily):
  - Determine trend direction (EMA slope, higher highs/lows)
  
LOWER TIMEFRAME (15m/1h):
  - Only take signals in direction of higher TF trend
  - Use any entry strategy (RSI, EMA cross, etc.)

LONG:  Higher TF uptrend + Lower TF buy signal
SHORT: Higher TF downtrend + Lower TF sell signal

EXIT:  Lower TF exit signal OR higher TF trend change
```

### Parameters
| Parameter | Default | Range to Test | Notes |
|-----------|---------|---------------|-------|
| `higher_tf` | 4h | 1h-1d | Trend determination |
| `lower_tf` | 15m | 5m-1h | Entry timing |
| `trend_ema` | 50 | 20-100 | EMA for trend direction |
| `entry_strategy` | RSI | Any | Lower TF entry method |

### When It Works
✅ Trending markets with clear direction  
✅ Pullback entries in strong trends  
✅ Reduces counter-trend mistakes

### When It Fails
❌ Transition periods between trends  
❌ Higher TF trend can change after entry  
❌ Fewer trading opportunities

### Realistic Expectations
- Win rate: 50-60%
- Fewer trades but higher quality
- Requires patience to wait for alignment
- Can miss moves that start counter-trend

---

## Strategy 9: Scalping with Order Flow (Advanced)

### The Idea
Use order book depth and recent trades to predict short-term price movement.

### Logic
```
IMBALANCE DETECTION:
  - Large bid wall = potential support
  - Large ask wall = potential resistance
  - Aggressive market buys = upward pressure
  - Aggressive market sells = downward pressure

LONG:  Bid side absorbing sells + uptick in price
SHORT: Ask side absorbing buys + downtick in price

EXIT:  Quick profit target (0.1-0.3%) OR time limit
```

### Why This Is Harder
- Requires real-time order book data
- Order book changes rapidly (walls can disappear)
- Spoofing is common (fake walls)
- Execution speed matters

### Parameters
| Parameter | Default | Notes |
|-----------|---------|-------|
| `depth_levels` | 10 | Order book depth to analyze |
| `imbalance_ratio` | 2.0 | Bid/ask volume ratio for signal |
| `profit_target` | 0.2% | Take profit quickly |
| `max_hold_time` | 60s | Exit if no movement |

### When It Works
✅ High-liquidity pairs with deep order books  
✅ Markets with genuine order flow (not wash traded)  
✅ Very short timeframes (seconds to minutes)

### When It Fails
❌ Most retail traders can't compete on speed  
❌ Order book data can be manipulated  
❌ Exchange fees can eat profits on small moves

### Realistic Expectations
- Very high win rate needed to overcome fees
- Requires excellent execution
- Not recommended for beginners
- Consider paper trading this extensively first

---

## Strategy 10: Grid Trading (Passive Income Approach)

### The Idea
Place multiple buy and sell orders at fixed intervals. Profit from price oscillation regardless of direction.

### Logic
```
SETUP:
  - Define price range (e.g., $40,000 - $50,000)
  - Divide into grid levels (e.g., every $500)
  - Place limit buys below current price
  - Place limit sells above current price

OPERATION:
  - When buy fills, place sell one grid level up
  - When sell fills, place buy one grid level down
  - Continuously cycle through the grid

PROFIT: Capture the spread between grid levels
```

### Parameters
| Parameter | Default | Notes |
|-----------|---------|-------|
| `grid_range` | 20% | Total price range covered |
| `grid_levels` | 20 | Number of grid lines |
| `per_grid_allocation` | 5% | Capital per grid position |

### When It Works
✅ Ranging markets with no clear direction  
✅ High volatility within a range  
✅ Pairs that mean-revert frequently

### When It Fails
❌ Strong trends (price exits grid, you're stuck)  
❌ One-way moves leave you with heavy bags  
❌ Capital intensive (money locked in orders)

### Realistic Expectations
- Can generate consistent small profits in ranges
- Catastrophic when price trends out of range
- Requires active management of grid boundaries
- Not "set and forget" despite appearances

---

## Comparing Strategies: Quick Reference

| Strategy | Win Rate | Trade Frequency | Best For | Complexity |
|----------|----------|-----------------|----------|------------|
| EMA Crossover | 35-45% | High | Trending markets | Low |
| RSI Mean Reversion | 55-65% | Medium | Ranging markets | Low |
| EMA + RSI | 50-60% | Medium | Pullbacks | Low |
| Bollinger Squeeze | 40-50% | Low | Breakouts | Medium |
| MACD Divergence | 45-55% | Low | Trend exhaustion | Medium |
| S/R Breakout | 35-45% | Low | Range breakouts | Medium |
| Volume Momentum | 40-50% | Medium | News moves | Medium |
| Multi-TF Alignment | 50-60% | Low | Strong trends | Medium |
| Order Flow Scalping | 55-65%* | Very High | Liquid markets | High |
| Grid Trading | 60-70%* | Varies | Ranges only | Medium |

*Higher win rates but lower expected value per trade

---

## General Advice for Strategy Development

### Start Simple
- Begin with EMA Crossover or RSI Mean Reversion
- Master one strategy before combining
- Add complexity only when simple fails

### Backtest Honestly
- Use out-of-sample data (don't test on data you optimized on)
- Include realistic fees (0.1% per trade typical for crypto)
- Account for slippage (especially on larger positions)
- Beware overfitting to historical data

### Risk Management Trumps Strategy
- A mediocre strategy with great risk management beats a great strategy with poor risk management
- Position sizing matters more than entry timing
- Always know your max loss before entering

### Keep Learning
- Track every trade with reasoning
- Review losing trades to understand failure modes
- Iterate parameters based on real results, not hypotheticals

---

## Suggested Learning Path

1. **Week 1-2**: Implement and backtest EMA Crossover
2. **Week 3-4**: Implement and backtest RSI Mean Reversion
3. **Week 5-6**: Implement EMA + RSI (your concept)
4. **Week 7-8**: Paper trade all three, compare results
5. **Month 2**: Add Bollinger Squeeze and Multi-TF
6. **Month 3+**: Iterate based on what's working

Remember: The goal isn't to find the "perfect" strategy. It's to find a strategy that:
- You understand completely
- Matches your risk tolerance
- Works in current market conditions
- You can execute consistently

Good luck, and remember to track everything!