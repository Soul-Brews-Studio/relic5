import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";
import { install } from "./report";

install();   // the page's own errors go to the hub (report.ts), and a stale page reloads itself after a deploy

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
