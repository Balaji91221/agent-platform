/**
 * The screen id a pathname belongs to.
 *
 * The stylesheet scopes rules by screen id (#chat, #agents, #mate), and the
 * crumb needs a title, so both read this one function rather than each parsing
 * the pathname their own way — `/agents/1` must not become id="agents/1".
 */
export function screenFor(pathname: string): string {
  const [, first = 'today', second] = pathname.split('/');
  if (first === 'agents' && second) return 'detail';
  return first || 'today';
}

export function titleFor(pathname: string, titles: Record<string, string>): string {
  return titles[screenFor(pathname)] ?? 'Dashboard';
}
