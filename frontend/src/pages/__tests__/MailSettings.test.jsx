import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MailSettings from "../MailSettings.jsx";

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MailSettings />
    </QueryClientProvider>,
  );
}

describe("MailSettings", () => {
  it("loads the saved SMTP config into the form", async () => {
    renderPage();
    // Heading is immediate; the form fills once the query resolves.
    expect(screen.getByText("Cấu hình Mail SMTP")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("shop@gmail.com")).toBeInTheDocument();
  });

  it("marks the password optional once one is already saved", async () => {
    renderPage();
    // has_password=true from the mock → placeholder switches to the dots hint.
    expect(await screen.findByPlaceholderText("••••••••••••")).toBeInTheDocument();
  });
});
