import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from 'react';
import { parseOperationsLink } from './operations-api';

const changed = 'innexq:navigate';
function subscribe(listener: () => void) {
  window.addEventListener('popstate', listener);
  window.addEventListener(changed, listener);
  return () => {
    window.removeEventListener('popstate', listener);
    window.removeEventListener(changed, listener);
  };
}

/** Keep the application and its memory-only sign-in alive while changing views. */
export function useLocationSearch() {
  return useSyncExternalStore(subscribe, () => window.location.search);
}

export function InternalLink({ onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  function navigate(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.currentTarget;
    if (anchor.hasAttribute('download') || (anchor.target && anchor.target !== '_self')) return;
    const destination = new URL(anchor.href);
    if (destination.origin !== window.location.origin || destination.pathname !== '/' || destination.hash ||
        (destination.search && 'invalid' in parseOperationsLink(destination.search))) return;
    event.preventDefault();
    window.history.pushState(null, '', destination.pathname + destination.search);
    window.dispatchEvent(new Event(changed));
  }
  return <a {...props} onClick={navigate} />;
}
