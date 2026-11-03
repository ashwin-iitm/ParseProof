import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import Layout from "@/components/Layout";
import { ToastProvider } from "@/components/toast";
import Runs from "@/pages/Runs";
import NewRun from "@/pages/NewRun";
import RunReview from "@/pages/RunReview";
import Templates from "@/pages/Templates";
import TemplateEditor from "@/pages/TemplateEditor";
import Settings from "@/pages/Settings";
import Batches from "@/pages/Batches";
import BatchDetail from "@/pages/BatchDetail";
import NotFound from "@/pages/NotFound";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Runs />} />
              <Route path="new" element={<NewRun />} />
              <Route path="batches" element={<Batches />} />
              <Route path="batches/:id" element={<BatchDetail />} />
              <Route path="templates" element={<Templates />} />
              <Route path="templates/:id" element={<TemplateEditor />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Route>
            <Route path="runs/:id" element={<RunReview />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
