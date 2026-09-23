import { Component, useEffect, useId, useRef, type PropsWithChildren } from "react";
import { useLocation } from "react-router-dom";

interface BoundaryProps extends PropsWithChildren {
  resetKey: string;
}

interface BoundaryState {
  resetKey: string;
  failed: boolean;
  chunkFailed: boolean;
}

function RouteErrorFallback({ chunkFailed, onRetry }: { chunkFailed: boolean; onRetry: () => void }) {
  const headingId = useId();
  const descriptionId = useId();
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    panel.current?.focus();
  }, []);

  return (
    <section
      ref={panel}
      role="alert"
      tabIndex={-1}
      aria-labelledby={headingId}
      aria-describedby={descriptionId}
      className="panel"
      style={{ maxWidth: 680, margin: "2rem auto", padding: "1.5rem" }}
    >
      <h2 id={headingId}>{chunkFailed ? "Page bundle could not load" : "This page could not be displayed"}</h2>
      <div id={descriptionId}>
        <p>{chunkFailed
          ? "A connection problem or an updated application may have interrupted loading. Try this page again. If it still fails, reload the application when you are ready."
          : "Try this page again or use navigation to open another page."}</p>
        <p>Retry redraws this page without reloading the application. Drafts stored outside the failed page are retained; unsaved fields within it may have been lost.</p>
        <p>Recovery does not resubmit actions. If an operation was in progress, check its status before submitting it again.</p>
        <p>Reloading the application may discard unsaved drafts across the workspace.</p>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
        <button type="button" className="button button--primary" onClick={onRetry}>Try page again</button>
        <button type="button" className="button button--ghost" onClick={() => window.location.reload()}>Reload application (may lose drafts)</button>
      </div>
    </section>
  );
}

class PageBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { resetKey: this.props.resetKey, failed: false, chunkFailed: false };

  static getDerivedStateFromProps(props: BoundaryProps, state: BoundaryState): Partial<BoundaryState> | null {
    return props.resetKey !== state.resetKey
      ? { resetKey: props.resetKey, failed: false, chunkFailed: false }
      : null;
  }

  static getDerivedStateFromError(error: unknown): Partial<BoundaryState> {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : "";
    return {
      failed: true,
      chunkFailed: /ChunkLoadError|Loading (?:CSS )?chunk .*failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(message),
    };
  }

  render() {
    if (this.state.failed) {
      return <RouteErrorFallback chunkFailed={this.state.chunkFailed} onRetry={() => this.setState({ failed: false, chunkFailed: false })} />;
    }
    return this.props.children;
  }
}

export function RouteErrorBoundary({ children }: PropsWithChildren) {
  const location = useLocation();
  // Reset errors on navigation, without keying/remounting healthy pages or their drafts.
  const resetKey = JSON.stringify([location.key, location.pathname, location.search, location.hash]);
  return <PageBoundary resetKey={resetKey}>{children}</PageBoundary>;
}
