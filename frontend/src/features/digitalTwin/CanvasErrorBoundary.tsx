import { Component, type ReactNode } from "react";

interface CanvasErrorBoundaryProps {
  children: ReactNode;
  /** Receives WebGL context, renderer and scene errors (thrown by Canvas or re-thrown from inside it). */
  onError: (error: unknown) => void;
}

interface CanvasErrorBoundaryState {
  failed: boolean;
}

/**
 * Isolates the 3D Canvas: a renderer failure never takes the Twin page (panels, inspector,
 * forms and drafts) down with it. The parent swaps in the 2D fallback via `onError`.
 */
export class CanvasErrorBoundary extends Component<CanvasErrorBoundaryProps, CanvasErrorBoundaryState> {
  state: CanvasErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): CanvasErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    this.props.onError(error);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
