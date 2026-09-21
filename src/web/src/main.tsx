import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { PublicClientApplication, BrowserCacheLocation, InteractionRequiredAuthError, type AccountInfo } from "@azure/msal-browser";
import { Button, FluentProvider, webLightTheme } from "@fluentui/react-components";
import { ControlRoom } from "./ControlRoom";
import { CustomerPortal } from "./CustomerPortal";
import { OperationsInbox } from "./OperationsInbox";
import { createRunApi, type WebConfig } from "./api";
import { createCustomerApi } from "./customer-api";
import { createOperationsApi } from "./operations-api";
import { createCaseReviewApi } from "./case-review-api";
import { isCustomerPortal, validateAppConfig } from "./app-mode";
import { useLocationSearch } from './navigation';
import "./control-room.css";

function App({ config, auth }: { config: WebConfig; auth: PublicClientApplication }) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const customer = isCustomerPortal(config);
  const search = useLocationSearch();
  const operations = !customer && new URLSearchParams(search).has('operations');
  const clients = useMemo(() => {
    const token = async () => {
    if (!account) throw new Error("Sign in to access your workspace.");
    try {
      return (await auth.acquireTokenSilent({ account, scopes: [config.apiScope] })).accessToken;
    } catch { throw new Error("Your session needs attention. Sign out and sign in again."); }
    };
    const caseToken = async () => {
      if (!account || customer) throw new Error('Operations sign-in required.');
      const request = { account, scopes: [config.apiScope.replace(/\/Runs\.Read$/, '/Cases.Manage')] };
      try { return (await auth.acquireTokenSilent(request)).accessToken; }
      catch (error) {
        if (!(error instanceof InteractionRequiredAuthError)) throw error;
        const result = await auth.acquireTokenPopup(request);
        if (result.account?.homeAccountId !== account.homeAccountId || result.account?.tenantId !== config.tenantId) throw new Error('Account changed. Sign in again.');
        return result.accessToken;
      }
    };
    return customer ? { customer: createCustomerApi(config, token), runs: null, operations: null, review: null } :
      { customer: null, runs: createRunApi(config, token), operations: createOperationsApi(config, token), review: createCaseReviewApi(config, token, caseToken) };
  }, [config, auth, account, customer]);

  async function signIn() {
    setBusy(true); setError("");
    try {
      const result = await auth.loginPopup({ scopes: [config.apiScope], prompt: "select_account" });
      if (result.account?.tenantId !== config.tenantId) throw new Error("Wrong tenant");
      auth.setActiveAccount(result.account); setAccount(result.account);
    } catch { setError("Sign-in did not complete. Allow the Microsoft sign-in popup and try again."); }
    finally { setBusy(false); }
  }
  function signOut() {
    const previous = account;
    setAccount(null); auth.setActiveAccount(null);
    void auth.logoutPopup({ account: previous, postLogoutRedirectUri: window.location.origin }).catch(() => {
      setError("InnexQ data was cleared. Microsoft sign-out did not complete; close this tab if using a shared device.");
    });
  }
  return <FluentProvider theme={webLightTheme}>
    {account ? customer && clients.customer ? <CustomerPortal key={account.homeAccountId} api={clients.customer} accountName={account.name || account.username} onSignOut={signOut} /> : operations && clients.operations && clients.review ? <OperationsInbox key={`${account.homeAccountId}:${search}`} api={clients.operations} reviewApi={clients.review} accountName={account.name || account.username} onSignOut={signOut} /> : clients.runs && clients.operations ? <ControlRoom key={`${account.homeAccountId}:${search}`} api={clients.runs} operationsApi={clients.operations} accountName={account.name || account.username} onSignOut={signOut} /> : null :
      <main className="sign-in"><p className="eyebrow">INNEXQ / {customer ? 'CUSTOMER PORTAL' : operations ? 'OPERATIONS' : 'CONTROL ROOM'}</p><h1>{customer ? <>Your equipment.<br />The documents you need.</> : <>Company knowledge.<br />Human authority.</>}</h1>
        <p>{customer ? 'Request an existing equipment certificate. Your account determines which equipment you can access.' : 'Inspect the evidence, decisions and outcomes behind every governed Run.'}</p>
        <p>{customer ? 'Certificate Fulfilment · Synthetic hackathon environment' : 'Contract Renewal · Synthetic hackathon environment · Read-only access'}</p>
        <Button appearance="primary" size="large" disabled={busy} onClick={() => void signIn()}>{busy ? "Signing in…" : "Sign in with Microsoft"}</Button>
        {error && <p role="alert">{error}</p>}<p>{customer ? 'Use your assigned customer account. Certificate release requires every policy check to pass.' : 'Use your authorized InnexQ account. Approvals stay in Teams.'}</p>
      </main>}
  </FluentProvider>;
}

async function start() {
  const response = await fetch("/config.json", { cache: "no-store", credentials: "omit" });
  if (!response.ok) throw new Error("Configuration unavailable");
  const config = validateAppConfig(await response.json() as WebConfig);
  const auth = new PublicClientApplication({
    auth: { clientId: config.clientId, authority: `https://login.microsoftonline.com/${config.tenantId}`, redirectUri: `${window.location.origin}/redirect.html` },
    cache: { cacheLocation: BrowserCacheLocation.MemoryStorage },
    system: { loggerOptions: { piiLoggingEnabled: false, loggerCallback: () => {} } },
  });
  await auth.initialize();
  createRoot(document.getElementById("root")!).render(<App config={config} auth={auth} />);
}
void start().catch(() => {
  document.getElementById("root")!.textContent = "InnexQ is not configured for sign-in yet. Please contact the application owner.";
});
