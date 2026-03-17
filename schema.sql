-- Run this in Supabase's SQL Editor
-- Go to supabase.com → your project → SQL Editor → New Query → paste this → Run

CREATE TABLE IF NOT EXISTS users (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(50) NOT NULL UNIQUE,
    password   VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name              VARCHAR(100) NOT NULL,
    price             NUMERIC(10, 2) NOT NULL,
    billing_cycle     VARCHAR(10) DEFAULT 'monthly' CHECK (billing_cycle IN ('monthly', 'yearly', 'weekly')),
    next_billing_date DATE NOT NULL,
    category          VARCHAR(50) DEFAULT 'General',
    created_at        TIMESTAMP DEFAULT NOW()
);