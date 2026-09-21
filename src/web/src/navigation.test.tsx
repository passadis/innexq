import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InternalLink, useLocationSearch } from './navigation';
import { parseOperationsLink } from './operations-api';

const id = '22222222-2222-4222-8222-222222222222';
function MemorySession() {
  const [account, setAccount] = useState('signed out');
  const search = useLocationSearch();
  const linked = search ? parseOperationsLink(search) : null;
  return <><button onClick={() => setAccount('Operations signed in')}>Sign in</button><p>{account}</p>
    <p>{linked ? 'invalid' in linked ? 'Invalid link' : `Case ${linked.requestId}` : 'Overview'}</p>
    <InternalLink href={`/?operations=${id}`}>Inspect case</InternalLink><InternalLink href="/">Overview link</InternalLink></>;
}
afterEach(() => { window.history.replaceState(null, '', '/'); vi.restoreAllMocks(); });

describe('in-memory employee navigation', () => {
  it('preserves the signed-in parent across case and overview navigation, and browser history', async () => {
    render(<MemorySession />);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    fireEvent.click(screen.getByRole('link', { name: 'Inspect case' }));
    expect(screen.getByText(`Case ${id}`)).toBeInTheDocument();
    expect(screen.getByText('Operations signed in')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Overview link' }));
    expect(screen.getByText('Overview')).toBeInTheDocument();
    act(() => window.history.back());
    await waitFor(() => expect(screen.getByText(`Case ${id}`)).toBeInTheDocument());
    expect(screen.getByText('Operations signed in')).toBeInTheDocument();
    act(() => window.history.forward());
    await waitFor(() => expect(screen.getByText('Overview')).toBeInTheDocument());
    expect(screen.getByText('Operations signed in')).toBeInTheDocument();
  });
  it('keeps external deep-link validation strict', () => {
    window.history.replaceState(null, '', `/?operations=${id}&run=${id}`);
    render(<MemorySession />);
    expect(screen.getByText('Invalid link')).toBeInTheDocument();
  });
  it('does not intercept modified clicks, external links, downloads or invalid destinations', () => {
    const push = vi.spyOn(window.history, 'pushState');
    // A parent suppresses jsdom's unsupported document navigation after the link handler.
    const view = render(<div onClick={event => event.preventDefault()}><InternalLink href={`/?operations=${id}`}>Link</InternalLink></div>);
    fireEvent.click(screen.getByRole('link'), { ctrlKey: true });
    fireEvent.click(screen.getByRole('link'), { metaKey: true });
    fireEvent.click(screen.getByRole('link'), { shiftKey: true });
    for (const props of [{ href: 'https://example.com/' }, { href: '/', target: '_blank' }, { href: '/', download: 'file' }, { href: '/?operations=invalid' }, { href: '/?operations=' + id + '&unexpected=value' }, { href: '/#main' }]) {
      view.rerender(<div onClick={event => event.preventDefault()}><InternalLink {...props}>Link</InternalLink></div>);
      fireEvent.click(screen.getByRole('link'));
    }
    expect(push).not.toHaveBeenCalled();
  });
});
