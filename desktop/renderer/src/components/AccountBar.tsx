import type { JSX } from 'react';

import type { Account, AccountType } from '../../../shared/types';

interface Props {
  account: Account | undefined;
  pending: boolean;
}

const CURRENCY_SYMBOL: Record<string, string> = {
  GBP: '£',
  USD: '$',
  EUR: '€',
  JPY: '¥',
};

/**
 * Fortrade's own word: its button reads "Switch to real", so a live
 * account is labelled REAL. UNKNOWN is neutral rather than alarming -- it
 * means the page has not yet shown which kind of account this is.
 */
const BADGE: Record<AccountType, { label: string; tone: string; title: string }> = {
  DEMO: {
    label: 'DEMO',
    tone: 'demo',
    title: 'Demo account: practice money',
  },
  LIVE: {
    label: 'REAL',
    tone: 'live',
    title: 'Real account: real money. Fortrader AI only reads it.',
  },
  UNKNOWN: {
    label: 'UNKNOWN',
    tone: 'unknown',
    title: 'Fortrade has not shown yet whether this is a demo or real account',
  },
};

function money(value: number, currency: string): string {
  const symbol = CURRENCY_SYMBOL[currency] ?? '';

  return `${value < 0 ? '-' : ''}${symbol}${Math.abs(value).toLocaleString(
    'en-GB',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 },
  )}`;
}

function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'positive' | 'negative';
}): JSX.Element {
  return (
    <div className="account-field">
      <span className="account-field__label">{label}</span>
      <span className={`account-field__value${tone ? ` is-${tone}` : ''}`}>
        {value}
      </span>
    </div>
  );
}

export function AccountBar({ account, pending }: Props): JSX.Element {
  if (!account) {
    return (
      <footer className="account-bar account-bar--empty">
        {pending
          ? 'Waiting for Fortrade account data — log in to Web Fortrader if prompted.'
          : 'Account data unavailable.'}
      </footer>
    );
  }

  const { currency } = account;
  const badge = BADGE[account.account_type];

  const pnlTone =
    account.open_pnl > 0 ? 'positive' : account.open_pnl < 0 ? 'negative' : undefined;

  return (
    <footer className="account-bar">
      <span className={`badge badge--${badge.tone}`} title={badge.title}>
        {badge.label}
      </span>

      <Field label="Balance" value={money(account.balance, currency)} />
      <Field label="Equity" value={money(account.equity, currency)} />
      <Field
        label="Open P&L"
        value={money(account.open_pnl, currency)}
        tone={pnlTone}
      />
      <Field label="Used Margin" value={money(account.used_margin, currency)} />
      <Field
        label="Available Margin"
        value={money(account.available_margin, currency)}
      />
    </footer>
  );
}
