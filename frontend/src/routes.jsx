import { lazy, Suspense } from "react";
import { Navigate, Outlet, createBrowserRouter, useLocation } from "react-router-dom";
import { Toaster } from "react-hot-toast";

import AppLayout from "./components/AppLayout.jsx";
import Loading from "./components/Loading.jsx";
import PageSkeleton from "./components/PageSkeleton.jsx";
import { AuthProvider, useAuth } from "./lib/AuthContext.jsx";

const Dashboard = lazy(() => import("./pages/Dashboard.jsx"));
const Orders = lazy(() => import("./pages/Orders.jsx"));
const Products = lazy(() => import("./pages/Products.jsx"));
const Sites = lazy(() => import("./pages/Sites.jsx"));
const Hostings = lazy(() => import("./pages/Hostings.jsx"));
const HealthChecks = lazy(() => import("./pages/HealthChecks.jsx"));
const Reports = lazy(() => import("./pages/Reports.jsx"));
const Login = lazy(() => import("./pages/Login.jsx"));

// Each lazy menu page shows a layout-shaped skeleton while its chunk loads,
// instead of a centered "Đang tải…" spinner. The fallback mirrors that page's
// shape (how many stat cards, whether it has a filter row) so the transition
// reads as the page itself arriving. Login is a plain form → the default
// branded loader is enough.
const wrap = (Page, fallback = <PageSkeleton />) => (
  <Suspense fallback={fallback}>
    <Page />
  </Suspense>
);

// Root layout: provides AuthContext to every route (needs to be inside the
// router so AuthProvider can call useNavigate for logout).
function RootLayout() {
  return (
    <AuthProvider>
      <Toaster position="top-right" />
      <Outlet />
    </AuthProvider>
  );
}

function RequireAuth({ children }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) return <Loading />;
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      {
        path: "/",
        element: (
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        ),
        children: [
          { index: true, element: wrap(Dashboard, <PageSkeleton stats={0} filters={false} />) },
          { path: "orders", element: wrap(Orders, <PageSkeleton stats={3} />) },
          { path: "products", element: wrap(Products, <PageSkeleton stats={3} />) },
          { path: "sites", element: wrap(Sites, <PageSkeleton stats={4} />) },
          { path: "hostings", element: wrap(Hostings, <PageSkeleton stats={0} />) },
          { path: "health-checks", element: wrap(HealthChecks, <PageSkeleton stats={4} />) },
          { path: "reports", element: wrap(Reports, <PageSkeleton stats={0} />) },
        ],
      },
      { path: "/login", element: wrap(Login, <Loading />) },
    ],
  },
]);
