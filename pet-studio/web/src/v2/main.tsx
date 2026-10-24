import { Component, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import "./v2.css";
import { Designer } from "./Designer";

/** A render error shows itself instead of blanking the page (and the agent's calls get it too). */
class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    (window as any).__designerError = String(this.state.error.stack ?? this.state.error);
    return <pre className="m-6 text-bad">{String(this.state.error.stack ?? this.state.error)}{"\n\n"}Reload the page to go on.</pre>;
  }
}

createRoot(document.getElementById("root")!).render(<Boundary><Designer /></Boundary>);
