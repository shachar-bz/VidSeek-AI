// The browser entry point: mount shared account state, the router, and the visual system.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AccountProvider } from "./auth";
import "@fontsource-variable/inter/wght.css";
import "./styles/index.css";

const container = document.getElementById("root");
if (!container) throw new Error("index.html is missing its #root element");

createRoot(container).render(
  <StrictMode>
    <AccountProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AccountProvider>
  </StrictMode>
);
