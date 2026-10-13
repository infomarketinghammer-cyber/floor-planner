import { createBrowserRouter } from 'react-router'
import { PublicOrApp, RedirectHome, RequireAuth } from './auth/RequireAuth.tsx'
import { AppLayout } from './components/AppLayout.tsx'
import { AdminPage } from './pages/admin/AdminPage.tsx'
import { HomePage } from './pages/HomePage.tsx'
import { LandingPage } from './pages/LandingPage.tsx'
import { LoginPage } from './pages/LoginPage.tsx'
import { ProjectPage } from './pages/ProjectPage.tsx'
import { RegisterPage } from './pages/RegisterPage.tsx'
import { TilesPage } from './pages/TilesPage.tsx'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <PublicOrApp publicPage={<LandingPage />} app={<AppLayout />} />,
    children: [{ index: true, element: <HomePage /> }],
  },
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          {
            element: <RequireAuth roles={['contractor', 'admin']} />,
            children: [
              { path: 'projects/:projectId', element: <ProjectPage /> },
              { path: 'tiles', element: <TilesPage /> },
            ],
          },
          {
            element: <RequireAuth roles={['admin']} />,
            children: [{ path: 'admin', element: <AdminPage /> }],
          },
        ],
      },
    ],
  },
  { path: '*', element: <RedirectHome /> },
])
