import type { BrokerConnector, BrokerFill, KalshiCreds, RecommendationLite } from './types.js';
import { paperFill } from '../paper.js';
import { submitKalshiAsUser } from '../venues/kalshi.js';

/** Default fallback connector — paper-fills using the recommendation's market price. */
function makePaperConnector(venue: 'polymarket' | 'kalshi' | 'gemini'): BrokerConnector {
  return {
    venue,
    async submitAsUser({ rec, maxSlippageBps }) {
      const fill = paperFill(
        {
          venue: rec.venue,
          market_id: rec.market_id,
          outcome: rec.outcome,
          side: rec.side,
          limit_price: rec.market_price + 0.01,
          size_usd: rec.suggested_size_usd,
          max_slippage_bps: maxSlippageBps,
          dry_run: true,
          idempotency_key: rec.rec_id,
        },
        rec.market_price,
      );
      return {
        rec_id: rec.rec_id,
        venue: rec.venue,
        market_id: rec.market_id,
        outcome: rec.outcome,
        side: rec.side,
        avg_price: fill.avg_price,
        filled_usd: fill.filled_usd,
        broker_ref: 'paper-' + rec.rec_id.slice(0, 8),
      } satisfies BrokerFill;
    },
  };
}

/**
 * Kalshi connector: submits a REAL order with the user's RSA API key against
 * whatever KALSHI_API_URL points at (the demo sandbox by default). Falls back
 * to paper when DRY_RUN is on or no real creds were supplied, so the default
 * demo path never risks money.
 */
function makeKalshiConnector(): BrokerConnector {
  const paper = makePaperConnector('kalshi');
  return {
    venue: 'kalshi',
    async submitAsUser(args) {
      const creds = args.creds as KalshiCreds;
      const dryRun = (process.env.DRY_RUN ?? 'true').toLowerCase() !== 'false';
      const hasCreds = Boolean(creds?.apiKeyId && creds?.privateKeyPem);
      if (dryRun || !hasCreds) {
        return paper.submitAsUser(args);
      }
      return submitKalshiAsUser(creds, args.rec, args.maxSlippageBps);
    },
  };
}

const REGISTRY: Record<string, BrokerConnector> = {
  polymarket: makePaperConnector('polymarket'),
  kalshi:     makeKalshiConnector(),
  gemini:     makePaperConnector('gemini'),
};

export function getBroker(venue: string): BrokerConnector {
  const b = REGISTRY[venue];
  if (!b) throw new Error(`no broker connector for venue ${venue}`);
  return b;
}

export type { BrokerConnector, BrokerFill, RecommendationLite };
