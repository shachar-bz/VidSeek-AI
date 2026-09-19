// The browser entry point: mount the router and nothing else.
//
// No stylesheet is imported here yet. The visual system is specified in
// frontend/DESIGN.md and has not been built; whoever builds it imports its entry
// stylesheet from this file.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";

const container = document.getElementById("root");
if (!container) throw new Error("index.html is missing its #root element");

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
);
