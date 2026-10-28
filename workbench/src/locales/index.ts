import { zh } from './zh';
import { en } from './en';
import type { Locale } from './types';

export { zh, en };
export type { Locale };
export type Language = 'zh' | 'en';
export type Theme = 'dark' | 'light';

export const locales: Record<Language, Locale> = { zh, en };
