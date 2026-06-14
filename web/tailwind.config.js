/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        midnight: '#0c1220',
        slate: { DEFAULT: '#151c2c', light: '#1e2738' },
        memo: { DEFAULT: '#f3efe4', ink: '#2a2520', muted: '#6b6560' },
        gold: { DEFAULT: '#c9a227', light: '#dfc04a', dark: '#a6841a' },
        edge: { yes: '#2d6a4f', no: '#9b2226' },
        chain: '#6b8afd',
        agent: '#7c5cbf',
        rail: '#1e1e1e',
        ink: { DEFAULT: '#171717', muted: '#525252', faint: '#a3a3a3' },
        surface: {
          DEFAULT: '#fafaf9',
          sidebar: '#f5f5f3',
          panel: '#ffffff',
        },
      },
      fontFamily: {
        display: ['var(--font-display)', 'Georgia', 'serif'],
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        memo: '0 4px 24px rgba(0, 0, 0, 0.35), 0 1px 0 rgba(255, 255, 255, 0.06) inset',
      },
      keyframes: {
        memoIn: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        memoIn: 'memoIn 0.45s ease-out forwards',
      },
    },
  },
  plugins: [],
};
