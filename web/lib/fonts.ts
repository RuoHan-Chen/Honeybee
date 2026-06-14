import { IBM_Plex_Mono, IBM_Plex_Sans, Newsreader } from 'next/font/google';

export const display = Newsreader({
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
});

export const sans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-sans',
  display: 'swap',
});

export const mono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
  display: 'swap',
});
