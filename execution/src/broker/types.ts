/**
 * Broker connector interface.
 *
 * The user's prediction-market credentials are passed PER CALL by the user's
 * frontend (e.g. retrieved from a connect-wallet flow). They are NEVER
 * persisted server-side. The agent's own keys are NEVER used to move user funds.
 */
export interface PolymarketCreds { apiKey: string; apiSecret: string; passphrase: string; funder: `0x${string}`; }
// Kalshi authenticates with an RSA API key (key id + private key), NOT
// email/password. Requests are RSA-PSS signed; see ../venues/kalshi.ts.
export interface KalshiCreds     { apiKeyId: string; privateKeyPem: string; }
export interface GeminiCreds     { apiKey: string; apiSecret: string; }

export type BrokerCreds =
  | { venue: 'polymarket'; creds: PolymarketCreds }
  | { venue: 'kalshi';     creds: KalshiCreds }
  | { venue: 'gemini';     creds: GeminiCreds };

export interface RecommendationLite {
  rec_id: string;
  venue: 'polymarket' | 'kalshi' | 'gemini';
  market_id: string;
  outcome: string;
  side: 'BUY' | 'SELL';
  market_price: number;
  fair_price: number;
  suggested_size_usd: number;
}

export interface BrokerFill {
  rec_id: string;
  venue: string;
  market_id: string;
  outcome: string;
  side: 'BUY' | 'SELL';
  avg_price: number;
  filled_usd: number;
  broker_ref: string;        // venue-side order id (off-chain)
}

export interface BrokerConnector {
  venue: 'polymarket' | 'kalshi' | 'gemini';
  submitAsUser(args: {
    creds: PolymarketCreds | KalshiCreds | GeminiCreds;
    rec: RecommendationLite;
    maxSlippageBps: number;
  }): Promise<BrokerFill>;
}
