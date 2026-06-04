import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";

import AppLayout from "./components/AppLayout.jsx";
import Loading from "./components/Loading.jsx";

const Dashboard = lazy(() => import("./pages/Dashboard.jsx"));
const Orders = lazy(() => import("./pages/Orders.jsx"));
const Products = lazy(() => import("./pages/Products.jsx"));
const Sites = lazy(() => import("./pages/Sites.jsx"));
const Login = lazy(() => import("./pages/Login.jsx"));

const wrap = (Page) => (
  <Suspense fallback={<Loading />}>
    <Page />
  </Suspense>
);

// RequireAuth is a pass-through placeholder until auth is built.
function RequireAuth({ children }) {
  return children;
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: wrap(Dashboard) },
      { path: "orders", element: wrap(Orders) },
      { path: "products", element: wrap(Products) },
      { path: "sites", element: wrap(Sites) },
    ],
  },
  { path: "/login", element: wrap(Login) },
]);
