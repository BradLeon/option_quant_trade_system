-- Supabase Database Schema for Option Quant Trade System
-- Run this script in the Supabase SQL Editor to create all required tables

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Stock Quotes Table
CREATE TABLE IF NOT EXISTS stock_quotes (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(18,4),
    high DECIMAL(18,4),
    low DECIMAL(18,4),
    close DECIMAL(18,4),
    volume BIGINT,
    turnover DECIMAL(18,2),
    source VARCHAR(20),  -- 'futu' or 'yahoo'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timestamp)
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_stock_quotes_symbol_timestamp
ON stock_quotes(symbol, timestamp DESC);

-- K-line Bars Table
CREATE TABLE IF NOT EXISTS kline_bars (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    ktype VARCHAR(10) NOT NULL,  -- 'day', '1min', '5min', '15min', '30min', '60min'
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(18,4),
    high DECIMAL(18,4),
    low DECIMAL(18,4),
    close DECIMAL(18,4),
    volume BIGINT,
    turnover DECIMAL(18,2),
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, ktype, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_kline_bars_symbol_ktype_timestamp
ON kline_bars(symbol, ktype, timestamp DESC);

-- Option Quotes Table
CREATE TABLE IF NOT EXISTS option_quotes (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    underlying VARCHAR(20) NOT NULL,
    option_type VARCHAR(4) NOT NULL,  -- 'call' or 'put'
    strike_price DECIMAL(18,4) NOT NULL,
    expiry_date DATE NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    last_price DECIMAL(18,4),
    bid DECIMAL(18,4),
    ask DECIMAL(18,4),
    volume BIGINT,
    open_interest BIGINT,
    iv DECIMAL(8,4),  -- implied volatility
    delta DECIMAL(8,4),
    gamma DECIMAL(8,4),
    theta DECIMAL(8,4),
    vega DECIMAL(8,4),
    rho DECIMAL(8,4),
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_option_quotes_underlying_expiry
ON option_quotes(underlying, expiry_date);

CREATE INDEX IF NOT EXISTS idx_option_quotes_symbol_timestamp
ON option_quotes(symbol, timestamp DESC);

-- Fundamentals Table
CREATE TABLE IF NOT EXISTS fundamentals (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    market_cap DECIMAL(20,2),
    pe_ratio DECIMAL(10,2),
    pb_ratio DECIMAL(10,2),
    ps_ratio DECIMAL(10,2),
    dividend_yield DECIMAL(8,4),
    eps DECIMAL(10,4),
    revenue DECIMAL(20,2),
    profit DECIMAL(20,2),
    debt_to_equity DECIMAL(10,4),
    current_ratio DECIMAL(10,4),
    roe DECIMAL(8,4),
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_symbol_date
ON fundamentals(symbol, date DESC);

-- Macro Data Table
CREATE TABLE IF NOT EXISTS macro_data (
    id BIGSERIAL PRIMARY KEY,
    indicator VARCHAR(50) NOT NULL,  -- e.g., 'VIX', 'TNX', 'SPY'
    date DATE NOT NULL,
    value DECIMAL(18,6),
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(indicator, date)
);

CREATE INDEX IF NOT EXISTS idx_macro_data_indicator_date
ON macro_data(indicator, date DESC);

-- Add Row Level Security (RLS) policies
-- Note: Adjust these based on your authentication strategy

ALTER TABLE stock_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE kline_bars ENABLE ROW LEVEL SECURITY;
ALTER TABLE option_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro_data ENABLE ROW LEVEL SECURITY;

-- Allow all operations for authenticated users (adjust as needed)
CREATE POLICY "Allow all for authenticated users" ON stock_quotes
    FOR ALL USING (true);

CREATE POLICY "Allow all for authenticated users" ON kline_bars
    FOR ALL USING (true);

CREATE POLICY "Allow all for authenticated users" ON option_quotes
    FOR ALL USING (true);

CREATE POLICY "Allow all for authenticated users" ON fundamentals
    FOR ALL USING (true);

CREATE POLICY "Allow all for authenticated users" ON macro_data
    FOR ALL USING (true);

-- Grant permissions to anon and authenticated roles
GRANT ALL ON stock_quotes TO anon, authenticated;
GRANT ALL ON kline_bars TO anon, authenticated;
GRANT ALL ON option_quotes TO anon, authenticated;
GRANT ALL ON fundamentals TO anon, authenticated;
GRANT ALL ON macro_data TO anon, authenticated;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
